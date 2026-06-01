"""Debug logging helper for agent instrumentation."""

from __future__ import annotations

import json
import time
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parents[2] / "debug-20ed5d.log"


def debug_log(
    location: str,
    message: str,
    data: dict | None = None,
    hypothesis_id: str = "",
    run_id: str = "pre-fix",
) -> None:
    payload = {
        "sessionId": "20ed5d",
        "runId": run_id,
        "hypothesisId": hypothesis_id,
        "location": location,
        "message": message,
        "data": data or {},
        "timestamp": int(time.time() * 1000),
    }
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload) + "\n")
