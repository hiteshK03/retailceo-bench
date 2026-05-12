"""Frontier model CEO harness — Anthropic / OpenAI-compatible providers."""

from __future__ import annotations

import os
import sys
import time
from typing import Any, Dict, List, Optional

from retailceo.models import CEOAction, CEOObservation, ProposalDecision
from .policies import CEOPolicy


class FrontierCEO(CEOPolicy):
    """CEO policy backed by a hosted frontier LLM.

    Uses the same prompt and JSON parser as baseline policies,
    so the reward it achieves is a fair comparison.
    """

    DEFAULT_MAX_TOKENS: int = 600

    def __init__(
        self,
        model: Optional[str] = None,
        provider: str = "auto",
        api_base: Optional[str] = None,
        api_key: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 0.0,
        max_retries: int = 3,
        request_timeout_s: float = 90.0,
        dual_head: bool = False,
        action_max_tokens: int = 300,
        journal_max_tokens: int = 400,
        permissive: bool = False,
    ):
        if max_tokens is None:
            max_tokens = self.DEFAULT_MAX_TOKENS
        provider = self._resolve_provider(provider, api_base, model)
        self._provider = provider

        if provider == "anthropic":
            self._init_anthropic(
                model=model,
                api_base=api_base,
                api_key=api_key,
                extra_headers=extra_headers,
                request_timeout_s=request_timeout_s,
            )
        elif provider == "openai":
            self._init_openai(
                model=model,
                api_base=api_base,
                api_key=api_key,
                request_timeout_s=request_timeout_s,
            )
        else:
            raise ValueError(f"Unknown provider: {provider!r}")

        self._max_tokens = max_tokens
        self._temperature = temperature
        self._max_retries = max_retries
        self._dual_head = dual_head
        self._action_max_tokens = action_max_tokens
        self._journal_max_tokens = journal_max_tokens
        self._permissive = permissive

        tag = f"frontier:{self._model.split('/')[-1]}"
        if dual_head:
            tag += "-dual"
        if permissive:
            tag += "-permissive"
        self.name = tag
        self.n_parse_errors = 0
        self.n_api_errors = 0
        self.total_tokens = 0
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0

    @staticmethod
    def _resolve_provider(
        provider: str, api_base: Optional[str], model: Optional[str]
    ) -> str:
        if provider != "auto":
            return provider
        if model and "claude" in model.lower():
            return "anthropic"
        if os.environ.get("ANTHROPIC_API_KEY"):
            return "anthropic"
        if os.environ.get("OPENAI_API_KEY"):
            return "openai"
        raise RuntimeError(
            "FrontierCEO provider=auto: cannot infer. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY, or pass provider= explicitly."
        )

    def _init_anthropic(self, model, api_base, api_key, extra_headers, request_timeout_s):
        try:
            import anthropic
        except ImportError as e:
            raise RuntimeError(
                "anthropic package required; pip install anthropic"
            ) from e
        key = api_key or os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise RuntimeError(
                "FrontierCEO(provider=anthropic) needs api_key or $ANTHROPIC_API_KEY"
            )
        base_url = api_base or os.environ.get("ANTHROPIC_BASE_URL") or None
        kwargs: Dict[str, Any] = {
            "api_key": key,
            "timeout": request_timeout_s,
        }
        if base_url:
            kwargs["base_url"] = base_url
        if extra_headers:
            kwargs["default_headers"] = extra_headers
        self._client = anthropic.Anthropic(**kwargs)
        self._model = model or "claude-sonnet-4-6-20250514"

    def _init_openai(self, model, api_base, api_key, request_timeout_s):
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError(
                "openai package required; pip install openai"
            ) from e
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "FrontierCEO(provider=openai) needs api_key or $OPENAI_API_KEY"
            )
        kwargs: Dict[str, Any] = {
            "api_key": key,
            "timeout": request_timeout_s,
        }
        if api_base:
            kwargs["base_url"] = api_base
        self._client = OpenAI(**kwargs)
        self._model = model or "gpt-4o"

    RETRY_PROMPT = (
        "Your previous response could not be parsed. "
        "Emit ONLY a JSON object inside <action>...</action> tags. "
        "No prose, no markdown, no explanation — just the JSON.\n"
        "<action>\n"
        '{"decisions": [{"proposal_id": "...", "verdict": "approve|reject|modify|request_info"}, ...], '
        '"budget_allocations": {"supply_chain": ..., "store_ops": ..., "finance": ..., "growth": ...}}\n'
        "</action>"
    )

    def act(self, obs, env=None, week=0):
        from retailceo.prompts import build_chat, parse_response

        if self._dual_head:
            return self._act_dual(obs, week=week)
        messages = build_chat(obs, token_budget=self._max_tokens)
        completion = self._call(messages, max_tokens=self._max_tokens)
        action, tel = parse_response(completion, obs.inbox)
        if not tel["parse_ok"] and not tel["parse_partial"]:
            action, tel = self._retry_parse(messages, completion, obs, tel)
        return action

    def _retry_parse(self, messages, bad_completion, obs, orig_tel):
        from retailceo.prompts import parse_response

        retry_messages = messages + [
            {"role": "assistant", "content": bad_completion},
            {"role": "user", "content": self.RETRY_PROMPT},
        ]
        print(
            f"[{self.name}] parse failed ({orig_tel.get('parse_error', '?')}), retrying…",
            file=sys.stderr,
        )
        completion2 = self._call(retry_messages, max_tokens=self._max_tokens)
        action2, tel2 = parse_response(completion2, obs.inbox)
        if tel2["parse_ok"] or tel2["parse_partial"]:
            return action2, tel2
        self.n_parse_errors += 1
        return action2, tel2

    def _act_dual(self, obs, week=0):
        from retailceo.prompts import (
            ACTION_SYSTEM_PROMPT_PERMISSIVE,
            build_action_chat,
            build_journal_chat,
            parse_response,
            parse_journal_response,
            render_observation,
        )

        act_messages = build_action_chat(obs)
        if self._permissive:
            act_messages = [
                {"role": "system", "content": ACTION_SYSTEM_PROMPT_PERMISSIVE},
                {"role": "user", "content": render_observation(obs)},
            ]
        act_text = self._call(act_messages, max_tokens=self._action_max_tokens)
        action, tel = parse_response(act_text, obs.inbox)
        if not tel["parse_ok"] and not tel["parse_partial"]:
            retry_messages = act_messages + [
                {"role": "assistant", "content": act_text},
                {"role": "user", "content": self.RETRY_PROMPT},
            ]
            print(
                f"[{self.name}] dual-head parse failed ({tel.get('parse_error', '?')}), retrying…",
                file=sys.stderr,
            )
            act_text2 = self._call(retry_messages, max_tokens=self._action_max_tokens)
            action2, tel2 = parse_response(act_text2, obs.inbox)
            if tel2["parse_ok"] or tel2["parse_partial"]:
                action, tel = action2, tel2
            else:
                self.n_parse_errors += 1

        jrn_messages = build_journal_chat(
            obs, action.decisions, action.budget_allocations,
        )
        jrn_text = self._call(jrn_messages, max_tokens=self._journal_max_tokens)
        action.journal_entry = parse_journal_response(jrn_text)
        return action

    def _call(self, messages: List[Dict[str, str]], max_tokens: Optional[int] = None) -> str:
        max_tokens = max_tokens if max_tokens is not None else self._max_tokens
        last_err: Optional[Exception] = None
        for attempt in range(self._max_retries):
            try:
                if self._provider == "anthropic":
                    return self._call_anthropic(messages, max_tokens=max_tokens)
                return self._call_openai(messages, max_tokens=max_tokens)
            except Exception as e:
                last_err = e
                if attempt + 1 < self._max_retries:
                    backoff = 2 ** attempt
                    print(
                        f"[{self.name}] api retry {attempt+1}/{self._max_retries} "
                        f"after {backoff}s: {type(e).__name__}: {str(e)[:140]}",
                        file=sys.stderr,
                    )
                    time.sleep(backoff)
                else:
                    self.n_api_errors += 1
        print(
            f"[{self.name}] giving up after {self._max_retries} retries: {last_err}",
            file=sys.stderr,
        )
        return ""

    def _call_openai(self, messages, max_tokens=None):
        r = self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            max_tokens=max_tokens or self._max_tokens,
            temperature=self._temperature,
        )
        if r.usage is not None:
            self.total_tokens += r.usage.total_tokens or 0
            self.total_prompt_tokens += r.usage.prompt_tokens or 0
            self.total_completion_tokens += r.usage.completion_tokens or 0
        return r.choices[0].message.content or ""

    def _call_anthropic(self, messages, max_tokens=None):
        system_parts = [m["content"] for m in messages if m.get("role") == "system"]
        turns = [m for m in messages if m.get("role") != "system"]
        system = "\n\n".join(system_parts) if system_parts else None
        r = self._client.messages.create(
            model=self._model,
            max_tokens=max_tokens or self._max_tokens,
            temperature=self._temperature,
            system=system,
            messages=turns,
        )
        usage = getattr(r, "usage", None)
        if usage is not None:
            in_tok = getattr(usage, "input_tokens", 0) or 0
            out_tok = getattr(usage, "output_tokens", 0) or 0
            self.total_prompt_tokens += in_tok
            self.total_completion_tokens += out_tok
            self.total_tokens += in_tok + out_tok
        text_parts: List[str] = []
        for block in r.content:
            if getattr(block, "type", "") == "text":
                text_parts.append(block.text)
        return "".join(text_parts)
