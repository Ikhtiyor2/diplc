from __future__ import annotations

from django.utils import timezone

from apps.core.grading import grade_objective
from apps.assessments.models import Question, TestAttempt


def grade_attempt(attempt: TestAttempt, answers: dict) -> TestAttempt:
    total = 0
    earned = 0
    needs_review = False
    details = {}
    for question in attempt.test.questions.all():
        total += question.points
        answer = answers.get(str(question.id), answers.get(question.id))
        payload = {"kind": question.type, **(question.payload or {})}
        if question.type == Question.Type.TEXT:
            needs_review = True
            details[str(question.id)] = {"answer": answer, "auto": False, "score": None}
            continue
        ratio, auto = grade_objective(payload, answer)
        score = round(ratio * question.points, 2)
        earned += score
        details[str(question.id)] = {"answer": answer, "auto": auto, "score": score}
    attempt.answers = {"raw": answers, "details": details}
    attempt.max_score = total
    if total:
        attempt.score = round(earned * 100 / total, 1)
    else:
        attempt.score = 0
    attempt.status = TestAttempt.Status.SUBMITTED if needs_review else TestAttempt.Status.GRADED
    attempt.submitted_at = timezone.now()
    attempt.save()
    return attempt


def grade_exercise(exercise, answers) -> float | None:
    from apps.core.grading import grade_objective

    payload = {"kind": exercise.type, **(exercise.content or {})}
    if exercise.type == "writing":
        return None
    if exercise.type in {"reading", "listening"}:
        questions = payload.get("questions") or []
        if not questions:
            return 0
        hits = 0
        given = answers if isinstance(answers, dict) else {}
        for index, question in enumerate(questions):
            ratio, _ = grade_objective({"kind": question.get("type", "single"), **question}, given.get(str(index)))
            hits += ratio
        return round(hits * 100 / len(questions), 1)
    ratio, auto = grade_objective(payload, answers)
    if not auto:
        return None
    return round(ratio * 100, 1)
