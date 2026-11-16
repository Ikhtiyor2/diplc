from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "action", "path", "ip_address")
    list_filter = ("action",)
    search_fields = ("path", "actor__login", "actor__last_name")
    readonly_fields = [field.name for field in AuditLog._meta.fields]
