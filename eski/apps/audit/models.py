from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    action = models.CharField(max_length=160)
    method = models.CharField(max_length=8)
    path = models.CharField(max_length=255)
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Событие журнала"
        verbose_name_plural = "Журнал действий"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        actor = self.actor.full_name if self.actor else "система"
        return f"{actor}: {self.action}"
