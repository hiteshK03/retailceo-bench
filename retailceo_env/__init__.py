"""RetailCEO environment for OpenEnv.

A framework-agnostic RL training environment that wraps the RetailCEO-Bench
simulator behind the OpenEnv HTTP/WebSocket interface. The action is text
(the model's raw weekly completion); the environment parses and scores it with
the same code the benchmark uses.

Train/eval separation: benchmark eval seeds (42-51) are reserved and refused by
the training env by default — see ``server.retailceo_environment`` for details.

Example:
    >>> from retailceo_env import RetailCEOEnv, CEOTextAction
    >>> with RetailCEOEnv(base_url="http://localhost:8000") as env:
    ...     result = env.reset(seed=123456)
    ...     result = env.step(CEOTextAction(completion=model_output))
    ...     print(result.reward, result.done)
"""

__all__ = ["RetailCEOEnv", "CEOTextAction", "CEOTextObservation"]


def __getattr__(name: str):
    if name == "RetailCEOEnv":
        from .client import RetailCEOEnv

        return RetailCEOEnv
    if name == "CEOTextAction":
        from .models import CEOTextAction

        return CEOTextAction
    if name == "CEOTextObservation":
        from .models import CEOTextObservation

        return CEOTextObservation
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
