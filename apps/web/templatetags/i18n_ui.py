from django import template
from django.utils.safestring import mark_safe

from apps.web.i18n import current_language, translate

register = template.Library()


@register.simple_tag
def t(message, **kwargs):
    return translate(message, **kwargs)


@register.filter(name="t")
def t_filter(message):
    return translate(message)


@register.simple_tag
def current_ui_language():
    return current_language()


@register.inclusion_tag("includes/language_switch.html", takes_context=True)
def language_switch(context):
    request = context.get("request")
    return {
        "request": request,
        "current_lang": current_language(),
    }


@register.simple_tag
def js_t(message):
    return mark_safe(translate(message).replace("\\", "\\\\").replace('"', '\\"'))
