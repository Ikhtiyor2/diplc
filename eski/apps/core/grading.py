from __future__ import annotations

import json
import re
from typing import Any


def _normalize(value: Any) -> Any:
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip().casefold()
    if isinstance(value, list):
        return sorted(_normalize(item) for item in value)
    if isinstance(value, dict):
        return {str(k): _normalize(v) for k, v in value.items()}
    return value


def _alternatives(correct: Any) -> list:
    if correct is None:
        return []
    if isinstance(correct, list):
        keys: list = []
        for item in correct:
            keys.extend(_alternatives(item))
        return keys
    text = str(correct).strip()
    if not text:
        return []
    parts = [part.strip() for part in re.split(r"\s*/\s*", text) if part.strip()]
    return parts or [text]

def grade_objective(payload: dict, answer: Any) -> tuple[float, bool]:
    """Return (ratio 0..1, is_auto)."""
    items = payload.get("items")
    if items:
        given = answer if isinstance(answer, list) else []
        hits = 0.0
        for index, item in enumerate(items):
            ratio, _ = grade_objective({"kind": "fill_blank", "correct": item.get("correct")}, given[index] if index < len(given) else "")
            hits += ratio
        return (hits / len(items) if items else 0.0, True)

    q_type = payload.get("kind") or payload.get("type")
    correct = payload.get("correct")
    if q_type in {"single", "vocabulary", "grammar", "tfng", "ynng", "short"}:
        alternatives = _alternatives(correct)
        ok = _normalize(answer) in [_normalize(item) for item in alternatives]
        return (1.0 if ok else 0.0, True)
    if q_type in {"multiple"}:
        expected = set(_normalize(correct or []))
        given = set(_normalize(answer or []))
        if not expected:
            return (0.0, True)
        return (1.0 if expected == given else 0.0, True)
    if q_type in {"fill_blank", "fill"}:
        alternatives = _alternatives(correct)
        ok = _normalize(answer) in [_normalize(item) for item in alternatives]
        return (1.0 if ok else 0.0, True)
    if q_type in {"match", "matching", "heading"}:
        expected = _normalize(correct or {})
        given = _normalize(answer or {})
        if not expected:
            return (0.0, True)
        hits = sum(1 for key, value in expected.items() if given.get(key) == value)
        return (hits / len(expected), True)
    if q_type in {"sentence_builder", "sentence"}:
        expected = payload.get("sentence") or correct
        if isinstance(expected, list):
            expected_text = " ".join(expected)
        else:
            expected_text = str(expected)
        given_text = " ".join(answer) if isinstance(answer, list) else str(answer or "")
        ok = _normalize(expected_text) == _normalize(given_text)
        return (1.0 if ok else 0.0, True)
    return (0.0, False)


def parse_json(raw: str | None, default=None):
    if not raw:
        return default if default is not None else {}
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return default if default is not None else {}
