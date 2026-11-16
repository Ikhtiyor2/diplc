from django.urls import include, path
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AssignmentViewSet,
    AttendanceViewSet,
    AuditLogViewSet,
    DashboardView,
    ExerciseViewSet,
    GroupViewSet,
    LanguageViewSet,
    LoginView,
    MeView,
    NotificationViewSet,
    QuestionViewSet,
    SubmissionViewSet,
    TelegramWebhookView,
    TestAttemptViewSet,
    TestViewSet,
    UserViewSet,
)

router = DefaultRouter()
router.register("users", UserViewSet, basename="users")
router.register("languages", LanguageViewSet, basename="languages")
router.register("groups", GroupViewSet, basename="groups")
router.register("attendance", AttendanceViewSet, basename="attendance")
router.register("assignments", AssignmentViewSet, basename="assignments")
router.register("submissions", SubmissionViewSet, basename="submissions")
router.register("tests", TestViewSet, basename="tests")
router.register("questions", QuestionViewSet, basename="questions")
router.register("test-results", TestAttemptViewSet, basename="test-results")
router.register("exercises", ExerciseViewSet, basename="exercises")
router.register("audit", AuditLogViewSet, basename="audit")
router.register("notifications", NotificationViewSet, basename="notifications")

urlpatterns = [
    path("auth/login/", LoginView.as_view(), name="api-login"),
    path("auth/refresh/", TokenRefreshView.as_view(), name="api-refresh"),
    path("auth/me/", MeView.as_view(), name="api-me"),
    path("dashboard/", DashboardView.as_view(), name="api-dashboard"),
    path("telegram/webhook/", TelegramWebhookView.as_view(), name="api-telegram-webhook"),
    path("", include(router.urls)),
]
