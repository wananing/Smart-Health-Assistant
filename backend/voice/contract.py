"""
Checker for the shared wire contract in ``contracts/voice-frames.json``.

The same rules are implemented in ``frontend/mock_voice_server.cjs``; together
they keep the gateway, the mock server and the browser client on one protocol.
Used by tests only.
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "contracts" / "voice-frames.json"

Direction = Literal["uplink", "downlink"]

_TYPE_CHECKS = {
    "string": lambda v: isinstance(v, str),
    # bool is an int subclass in Python; JSON keeps them apart.
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "object": lambda v: isinstance(v, dict),
    "array": lambda v: isinstance(v, list),
    "null": lambda v: v is None,
}


@lru_cache(maxsize=1)
def load_contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def contract_violations(frame: Any, direction: Direction) -> list[str]:
    """Every way ``frame`` breaks the contract; empty when it conforms."""
    if not isinstance(frame, dict):
        return [f"{direction} frame is not an object"]
    frame_type = frame.get("type")
    spec = load_contract()[direction].get(frame_type)
    if spec is None:
        return [f"{direction} frame type {frame_type!r} is not in the contract"]

    fields: dict[str, str] = spec.get("fields", {})
    optional = set(spec.get("optional", ()))
    enums: dict[str, list] = spec.get("enum", {})
    problems = []
    for name, value in frame.items():
        if name == "type":
            continue
        if name not in fields:
            problems.append(f"{frame_type}: unexpected field {name!r}")
            continue
        allowed = fields[name].split("|")
        if not any(_TYPE_CHECKS[t](value) for t in allowed):
            problems.append(f"{frame_type}.{name}: expected {fields[name]}, got {type(value).__name__}")
        elif name in enums and value not in enums[name]:
            problems.append(f"{frame_type}.{name}: {value!r} not in {enums[name]}")
    for name in fields:
        if name not in optional and name not in frame:
            problems.append(f"{frame_type}: missing field {name!r}")
    return problems
