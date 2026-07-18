"""FastAPI app exposing the RetailCEO environment over HTTP + WebSocket.

Run locally:
    uvicorn retailceo_env.server.app:app --host 0.0.0.0 --port 8000

Or, from inside the package dir (standalone layout, as Docker does):
    uvicorn server.app:app --host 0.0.0.0 --port 8000

Episode configuration is read from environment variables so one image serves
every difficulty/horizon:
    RETAILCEO_DIFFICULTY   easy | medium | hard         (default: medium)
    RETAILCEO_WEEKS        episode length in weeks       (default: 12)
    RETAILCEO_YEARS        multi-year horizon, overrides weeks (default: 0)
    RETAILCEO_CRISIS_PROB  per-crisis fire probability   (default: 0.85)
    RETAILCEO_START_CASH   starting cash in INR          (default: 2e8)
    RETAILCEO_ALLOW_EVAL_SEEDS  "1" to permit reserved eval seeds (default: 0)
"""

from __future__ import annotations

import os

from openenv.core.env_server import create_app

try:
    from ..models import CEOTextAction, CEOTextObservation
    from .retailceo_environment import RetailCEOEnvironment
except ImportError as e:
    if "relative import" not in str(e) and "no known parent package" not in str(e):
        raise
    from models import CEOTextAction, CEOTextObservation  # type: ignore
    from server.retailceo_environment import RetailCEOEnvironment  # type: ignore


def _cfg_from_env() -> dict:
    return {
        "difficulty": os.environ.get("RETAILCEO_DIFFICULTY", "medium"),
        "weeks": int(os.environ.get("RETAILCEO_WEEKS", "12")),
        "horizon_years": int(os.environ.get("RETAILCEO_YEARS", "0")),
        "crisis_prob": float(os.environ.get("RETAILCEO_CRISIS_PROB", "0.85")),
        "starting_cash_inr": float(os.environ.get("RETAILCEO_START_CASH", "2e8")),
        "allow_eval_seeds": os.environ.get("RETAILCEO_ALLOW_EVAL_SEEDS", "0") == "1",
    }


_CONFIG = _cfg_from_env()


def create_environment() -> RetailCEOEnvironment:
    """Factory (fresh env per WebSocket session)."""
    return RetailCEOEnvironment(**_CONFIG)


app = create_app(
    create_environment,
    CEOTextAction,
    CEOTextObservation,
    env_name="retailceo_env",
)


@app.get("/config")
def get_config() -> dict:
    return dict(_CONFIG)


def main() -> None:
    import uvicorn

    print("=" * 60)
    print("RetailCEO OpenEnv Environment Server")
    print("=" * 60)
    for k, v in _CONFIG.items():
        print(f"  {k}: {v}")
    print("  reserved eval seeds: 42-51 (refused unless allow_eval_seeds)")
    print("=" * 60)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))


if __name__ == "__main__":
    main()
