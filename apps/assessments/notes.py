from __future__ import annotations

import re
from html import escape

from django.utils.safestring import mark_safe

BLANK_RE = re.compile(r"\{(\d+)\}")


def blank_numbers(body: str) -> list[int]:
    seen: list[int] = []
    for match in BLANK_RE.finditer(body or ""):
        number = int(match.group(1))
        if number not in seen:
            seen.append(number)
    return seen


def blank_count(body: str) -> int:
    return len(blank_numbers(body))


def parse_answer_list(raw) -> list[list[str]]:
    if raw is None:
        return []
    if isinstance(raw, list):
        values = raw
    else:
        values = [part.strip() for part in str(raw).split(",") if part.strip()]
    cleaned: list[list[str]] = []
    for value in values:
        if isinstance(value, list):
            alts = [str(item).strip() for item in value if str(item).strip()]
        else:
            text = str(value).strip()
            alts = [part.strip() for part in re.split(r"\s*/\s*", text) if part.strip()]
        if alts:
            cleaned.append(alts)
    return cleaned


def items_from_notes(body: str, answers) -> list[dict]:
    numbers = blank_numbers(body)
    parsed = parse_answer_list(answers)
    items = []
    for index, number in enumerate(numbers or range(1, len(parsed) + 1)):
        correct = parsed[index] if index < len(parsed) else []
        items.append({"n": number, "prompt": f"Q{number}", "correct": correct})
    return items


def answers_text(items) -> str:
    parts = []
    for item in items or []:
        correct = item.get("correct")
        if isinstance(correct, list):
            parts.append("/".join(str(value) for value in correct if str(value).strip()))
        elif correct:
            parts.append(str(correct))
    return ", ".join(parts)


def _blank_html(display: int, name: str) -> str:
    return (
        f'<span class="nb-num">{display}</span>'
        f'<input class="nb-input" name="{escape(name, quote=True)}" '
        f'id="qnav-{display}" data-qnav="{display}" autocomplete="off">'
    )


def render_notes_html(body: str, field_prefix: str, start: int = 1) -> str:
    index_by = {number: index for index, number in enumerate(blank_numbers(body))}
    blocks: list[str] = []
    for raw_line in (body or "").split("\n"):
        line = raw_line.rstrip()
        if not line.strip():
            continue
        if line.strip().startswith("##"):
            blocks.append(f'<div class="nb-section">{escape(line.strip()[2:].strip())}</div>')
            continue
        is_bullet = line.lstrip().startswith("*")
        cleaned = re.sub(r"^\s*\*\s*", "", line)

        def replace(match: re.Match) -> str:
            number = int(match.group(1))
            index = index_by.get(number, 0)
            display = start + index
            return _blank_html(display, f"{field_prefix}_{index}")

        rendered = BLANK_RE.sub(replace, escape(cleaned))
        css = "nb-line nb-bullet" if is_bullet else "nb-line"
        blocks.append(f'<div class="{css}">{rendered}</div>')
    return mark_safe("".join(blocks))
