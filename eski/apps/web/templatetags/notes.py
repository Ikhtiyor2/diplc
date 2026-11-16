from django import template

from apps.assessments.notes import render_notes_html

register = template.Library()


@register.simple_tag
def notes_form(question, start=1):
    payload = question.payload or {}
    return render_notes_html(payload.get("body") or "", f"q_{question.id}", int(start or 1))
