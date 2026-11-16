from django.contrib import admin

from .models import TelegramLink, User


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("login", "last_name", "first_name", "middle_name", "role", "is_primary_admin", "faculty", "course", "profile_completed", "is_active")
    list_filter = ("role", "is_primary_admin", "is_active", "profile_completed")
    search_fields = ("login", "first_name", "last_name", "middle_name", "faculty")
    ordering = ("last_name", "first_name")


@admin.register(TelegramLink)
class TelegramLinkAdmin(admin.ModelAdmin):
    list_display = ("user", "code", "expires_at")
