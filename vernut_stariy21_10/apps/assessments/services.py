from __future__ import annotations

from apps.assessments.models import Question, Test, TestSection
from apps.assessments.notes import answers_text, items_from_notes, parse_answer_list


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [item for item in value if str(item).strip()]
    if isinstance(value, str):
        parsed = parse_answer_list(value)
        if len(parsed) == 1:
            return parsed[0]
        return [item.strip() for item in value.split(",") if item.strip()]
    return [value]


def payload_from_builder(item: dict) -> dict:
    q_type = item.get("type") or Question.Type.SINGLE
    if q_type == Question.Type.SINGLE:
        items = [row for row in (item.get("items") or []) if (row.get("stem") or row.get("stmt") or "").strip()]
        if items:
            return {
                "items": [
                    {
                        "stem": (row.get("stem") or row.get("stmt") or "").strip(),
                        "options": row.get("options") or item.get("options") or [],
                        "correct": row.get("correct", ""),
                    }
                    for row in items
                ]
            }
        return {"options": item.get("options") or [], "correct": item.get("correct", "")}
    if q_type == Question.Type.MULTIPLE:
        return {"options": item.get("options") or [], "correct": _as_list(item.get("correct"))}
    if q_type in {Question.Type.TFNG, Question.Type.YNNG}:
        items = [row for row in (item.get("items") or []) if (row.get("stmt") or row.get("prompt") or "").strip()]
        if items:
            return {
                "items": [
                    {"stmt": (row.get("stmt") or row.get("prompt") or "").strip(), "correct": row.get("correct", "")}
                    for row in items
                ]
            }
        return {"correct": item.get("correct", "")}
    if q_type in {Question.Type.FILL_BLANK, Question.Type.SHORT}:
        body = (item.get("body") or "").strip()
        title = (item.get("title") or "").strip()
        if body:
            answers = item.get("answers")
            if not answers:
                answers = [row.get("correct") for row in (item.get("items") or [])]
            notes_items = items_from_notes(body, answers)
            return {
                "layout": "notes",
                "title": title,
                "body": body,
                "intro": item.get("intro") or "",
                "items": notes_items,
            }
        items = item.get("items") or []
        cleaned = []
        for row in items:
            prompt = (row.get("prompt") or row.get("stmt") or "").strip()
            correct = _as_list(row.get("correct"))
            if prompt or correct:
                cleaned.append({"prompt": prompt, "correct": correct})
        if cleaned:
            return {"items": cleaned, "intro": item.get("intro") or ""}
        return {"correct": _as_list(item.get("correct"))}
    if q_type in {Question.Type.MATCH, Question.Type.HEADING}:
        left = [row.strip() for row in (item.get("left") or []) if str(row).strip()]
        right = [row.strip() for row in (item.get("right") or []) if str(row).strip()]
        correct = item.get("correct") or {}
        if isinstance(correct, list):
            correct = {left[index]: value for index, value in enumerate(correct) if index < len(left)}
        return {"left": left, "right": right, "correct": correct, "intro": item.get("intro") or ""}
    return item.get("payload") or {}


def builder_state(test: Test) -> dict:
    sections = []
    for section in test.sections.all():
        sections.append(
            {
                "id": f"s{section.id}",
                "db_id": section.id,
                "title": section.title,
                "kind": section.kind,
                "body": section.body,
                "audio_url": section.audio.url if section.audio else "",
            }
        )
    if not sections:
        sections = [{"id": "s_main", "db_id": None, "title": "Задания", "kind": "passage", "body": "", "audio_url": ""}]
    questions = []
    for question in test.questions.all():
        payload = question.payload or {}
        section_id = f"s{question.section_id}" if question.section_id else sections[0]["id"]
        items = payload.get("items") or []
        if question.type in {Question.Type.TFNG, Question.Type.YNNG} and not items:
            items = [{"stmt": question.question_text, "correct": payload.get("correct", "")}]
            text = ""
        else:
            text = question.question_text
        if question.type == Question.Type.SINGLE and not any(row.get("stem") for row in items):
            items = items or [{"stem": "", "options": payload.get("options") or ["", "", ""], "correct": payload.get("correct", "")}]
        questions.append(
            {
                "id": f"q{question.id}",
                "db_id": question.id,
                "sectionId": section_id,
                "type": question.type,
                "text": text,
                "intro": payload.get("intro") or "",
                "title": payload.get("title") or "",
                "body": payload.get("body") or "",
                "answers": answers_text(items) if payload.get("body") else "",
                "points": question.points,
                "options": payload.get("options") or ["", "", ""],
                "correct": payload.get("correct") or "",
                "left": payload.get("left") or ["", ""],
                "right": payload.get("right") or ["", ""],
                "items": items
                or (
                    [{"prompt": "", "correct": payload.get("correct", "")}]
                    if question.type in {"fill_blank", "short"}
                    else []
                ),
            }
        )
    return {"kind": test.kind, "sections": sections, "questions": questions}


def save_builder(test: Test, data: dict, files) -> Test:
    kind = data.get("kind") or test.kind
    if kind in Test.Kind.values:
        test.kind = kind
        test.save(update_fields=["kind"])

    sections_data = data.get("sections") or []
    id_map: dict[str, TestSection] = {}
    keep_sections: list[int] = []
    for index, item in enumerate(sections_data, start=1):
        db_id = item.get("db_id")
        defaults = {
            "title": (item.get("title") or f"Секция {index}").strip(),
            "kind": item.get("kind") or TestSection.Kind.PASSAGE,
            "body": item.get("body") or "",
            "order": index,
        }
        if db_id:
            section = TestSection.objects.filter(pk=db_id, test=test).first()
            if section:
                for key, value in defaults.items():
                    setattr(section, key, value)
                section.save()
            else:
                section = TestSection.objects.create(test=test, **defaults)
        else:
            section = TestSection.objects.create(test=test, **defaults)
        upload = files.get(f"audio_{item.get('id')}")
        if upload:
            section.audio = upload
            section.save(update_fields=["audio"])
        id_map[str(item.get("id"))] = section
        keep_sections.append(section.id)
    TestSection.objects.filter(test=test).exclude(id__in=keep_sections).delete()

    keep_questions: list[int] = []
    for index, item in enumerate(data.get("questions") or [], start=1):
        payload = payload_from_builder(item)
        q_type = item.get("type") or Question.Type.SINGLE
        text = (item.get("text") or "").strip()
        if not text:
            if q_type == Question.Type.FILL_BLANK and payload.get("body"):
                title = payload.get("title") or item.get("title") or f"Questions {index}"
                text = f"Complete the notes. {title}".strip()
            elif payload.get("items"):
                text = item.get("type") or f"Вопрос {index}"
            elif q_type in {Question.Type.MATCH, Question.Type.HEADING}:
                text = item.get("type") or f"Вопрос {index}"
            else:
                continue
        section = id_map.get(str(item.get("sectionId")))
        span = len(payload.get("items") or []) or 1
        if q_type in {Question.Type.MATCH, Question.Type.HEADING}:
            span = len(payload.get("left") or []) or 1
        defaults = {
            "section": section,
            "type": q_type,
            "question_text": text,
            "payload": payload,
            "points": int(item.get("points") or span) if not payload.get("body") else span,
            "order": index,
        }
        if payload.get("body"):
            defaults["points"] = max(span, 1)
        db_id = item.get("db_id")
        if db_id:
            question = Question.objects.filter(pk=db_id, test=test).first()
            if question:
                for key, value in defaults.items():
                    setattr(question, key, value)
                question.save()
            else:
                question = Question.objects.create(test=test, **defaults)
        else:
            question = Question.objects.create(test=test, **defaults)
        keep_questions.append(question.id)
    Question.objects.filter(test=test).exclude(id__in=keep_questions).delete()
    return test
