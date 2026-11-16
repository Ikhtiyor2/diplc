from django.utils import timezone
from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied as APIPermissionDenied
from rest_framework.decorators import action
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken

from apps.accounts.login_guard import clear_login_failures, login_blocked, record_login_failure
from apps.accounts.models import User
from apps.assessments.models import Question, Test, TestAttempt
from apps.attendance.models import Attendance
from apps.audit.models import AuditLog
from apps.core.credentials import generate_login, generate_password
from apps.core.exports import export_attendance, export_grades
from apps.core.metrics import assignment_progress, attendance_by_month, attendance_percent, average_score, group_performance
from apps.core.scoping import scoped_groups, scoped_students
from apps.core.services import grade_attempt, grade_exercise
from apps.groups.models import Enrollment, Group, Language
from apps.homework.models import Assignment, AssignmentFile, AssignmentItem, Submission, SubmissionFile
from apps.notifications.models import Notification
from apps.notifications.telegram import process_telegram_update
from apps.practice.models import Exercise, ExerciseAttempt

from .permissions import IsAdminRole, IsStaffRole, ReadOnlyOrStaff
from .serializers import (
    AssignmentSerializer,
    AttendanceSerializer,
    AuditLogSerializer,
    CredentialsSerializer,
    EnrollmentSerializer,
    ExerciseAttemptSerializer,
    ExerciseSerializer,
    GroupSerializer,
    LanguageSerializer,
    NotificationSerializer,
    QuestionSerializer,
    ReviewSerializer,
    SubmissionSerializer,
    TestAttemptSerializer,
    TestSerializer,
    TokenObtainPairByLoginSerializer,
    UserSerializer,
    UserWriteSerializer,
)


class LoginView(APIView):
    permission_classes = [AllowAny]
    serializer_class = TokenObtainPairByLoginSerializer

    def post(self, request):
        serializer = TokenObtainPairByLoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        login = serializer.validated_data["login"].strip()
        password = serializer.validated_data["password"]
        if login_blocked(request, login):
            return Response({"detail": "Слишком много попыток входа. Подождите 15 минут."}, status=status.HTTP_429_TOO_MANY_REQUESTS)
        user = User.objects.filter(login__iexact=login, is_active=True).first()
        if user is None:
            User().set_password(password)
            record_login_failure(request, login)
            return Response({"detail": "Неверный логин или пароль."}, status=status.HTTP_400_BAD_REQUEST)
        if not user.check_password(password):
            record_login_failure(request, login)
            return Response({"detail": "Неверный логин или пароль."}, status=status.HTTP_400_BAD_REQUEST)
        clear_login_failures(request, login)
        refresh = RefreshToken.for_user(user)
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserSerializer(user).data,
            }
        )


class MeView(APIView):
    def get(self, request):
        return Response(UserSerializer(request.user).data)


class UserViewSet(viewsets.ModelViewSet):
    queryset = User.objects.all()
    serializer_class = UserSerializer
    permission_classes = [IsAdminRole]
    search_fields = ["first_name", "last_name", "login"]
    filterset_fields = ["role", "is_active"]

    def get_serializer_class(self):
        if self.action in {"create", "update", "partial_update"}:
            return UserWriteSerializer
        return UserSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        if self.request.user.is_teaching_staff:
            return scoped_students(self.request.user)
        return qs

    def perform_create(self, serializer):
        self._guard_admin_role(serializer.validated_data.get("role"))
        user = serializer.save()
        self._normalize_created_admin(user)

    def perform_update(self, serializer):
        instance = serializer.instance
        role = serializer.validated_data.get("role", instance.role)
        if instance.is_primary_admin and not self.request.user.is_primary_admin:
            raise APIPermissionDenied("Главного администратора может менять только он сам.")
        if role == User.Role.ADMIN and not instance.is_admin:
            self._guard_admin_role(role)
        user = serializer.save()
        self._normalize_created_admin(user)

    def _guard_admin_role(self, role):
        if role == User.Role.ADMIN and not self.request.user.is_primary_admin:
            raise APIPermissionDenied("Новых администраторов добавляет только главный админ.")

    def _normalize_created_admin(self, user):
        if user.role == User.Role.ADMIN and not user.is_primary_admin:
            user.is_staff = False
            user.is_superuser = False
            user.save(update_fields=["is_staff", "is_superuser"])

    @action(detail=False, methods=["post"], url_path="generate")
    def generate(self, request):
        serializer = CredentialsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data["role"] == User.Role.ADMIN and not request.user.is_primary_admin:
            return Response({"detail": "Новых администраторов добавляет только главный админ."}, status=status.HTTP_403_FORBIDDEN)
        login = generate_login(data["last_name"], data["first_name"], data["role"])
        password = generate_password()
        user = User.objects.create_user(
            login=login,
            password=password,
            first_name=data["first_name"],
            last_name=data["last_name"],
            role=data["role"],
            phone=data.get("phone", ""),
            must_change_password=True,
            is_staff=False,
            is_primary_admin=False,
        )
        return Response({"user": UserSerializer(user).data, "password": password}, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=["get"], permission_classes=[IsStaffRole])
    def students(self, request):
        qs = scoped_students(request.user)
        query = request.query_params.get("q", "").strip()
        if query:
            qs = qs.filter(last_name__icontains=query) | qs.filter(first_name__icontains=query) | qs.filter(login__icontains=query)
        page = self.paginate_queryset(qs.distinct())
        serializer = UserSerializer(page or qs.distinct()[:25], many=True)
        if page is not None:
            return self.get_paginated_response(serializer.data)
        return Response(serializer.data)


class LanguageViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = Language.objects.all()
    serializer_class = LanguageSerializer
    permission_classes = [IsAuthenticated]


class GroupViewSet(viewsets.ModelViewSet):
    serializer_class = GroupSerializer
    permission_classes = [ReadOnlyOrStaff]
    search_fields = ["name"]
    filterset_fields = ["language", "teacher", "level", "is_active"]

    def get_queryset(self):
        return scoped_groups(self.request.user)

    @action(detail=True, methods=["post"], permission_classes=[IsAdminRole])
    def enroll(self, request, pk=None):
        group = self.get_object()
        serializer = EnrollmentSerializer(data={**request.data, "group": group.id})
        serializer.is_valid(raise_exception=True)
        serializer.save(group=group)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["get"], url_path="journal")
    def journal(self, request, pk=None):
        group = self.get_object()
        students = scoped_students(request.user).filter(enrollments__group=group).distinct()
        payload = []
        for student in students:
            progress = assignment_progress(student, group)
            payload.append(
                {
                    "student": UserSerializer(student).data,
                    "attendance": attendance_percent(student, group),
                    "average": average_score(student, group),
                    "assignments_done": progress["done"],
                    "assignments_pending": progress["pending"],
                }
            )
        return Response({"group": GroupSerializer(group).data, "rows": payload})

    @action(detail=True, methods=["get"], url_path="export/attendance")
    def export_attendance_xlsx(self, request, pk=None):
        return export_attendance(self.get_object())

    @action(detail=True, methods=["get"], url_path="export/grades")
    def export_grades_xlsx(self, request, pk=None):
        return export_grades(self.get_object())


class AttendanceViewSet(viewsets.ModelViewSet):
    serializer_class = AttendanceSerializer
    permission_classes = [IsStaffRole]
    filterset_fields = ["group", "student", "lesson_date", "status"]

    def get_queryset(self):
        qs = Attendance.objects.select_related("student", "group")
        if self.request.user.is_admin:
            return qs
        return qs.filter(group__teacher=self.request.user)

    def perform_create(self, serializer):
        serializer.save(marked_by=self.request.user)

    @action(detail=False, methods=["post"], url_path="bulk")
    def bulk(self, request):
        group_id = request.data.get("group")
        lesson_date = request.data.get("lesson_date")
        marks = request.data.get("marks", [])
        group = scoped_groups(request.user).filter(pk=group_id).first()
        if not group:
            return Response({"detail": "Группа не найдена."}, status=404)
        created = []
        for mark in marks:
            from apps.attendance.models import Attendance

            rec, _ = Attendance.objects.update_or_create(
                student_id=mark["student"],
                group=group,
                lesson_date=lesson_date,
                kind=Attendance.Kind.CLASS,
                defaults={"status": mark["status"], "comment": mark.get("comment", ""), "marked_by": request.user},
            )
            created.append(rec)
        return Response(AttendanceSerializer(created, many=True).data)


class AssignmentViewSet(viewsets.ModelViewSet):
    serializer_class = AssignmentSerializer
    permission_classes = [ReadOnlyOrStaff]
    parser_classes = [JSONParser, MultiPartParser, FormParser]
    filterset_fields = ["group", "is_published"]
    search_fields = ["title"]

    def get_queryset(self):
        qs = Assignment.objects.select_related("group", "created_by").prefetch_related("files", "items")
        user = self.request.user
        if user.is_admin:
            return qs
        if user.is_teaching_staff:
            return qs.filter(group__teacher=user)
        return qs.filter(group__enrollments__student=user, is_published=True).distinct()

    def perform_create(self, serializer):
        assignment = serializer.save(created_by=self.request.user)
        for uploaded in self.request.FILES.getlist("files"):
            AssignmentFile.objects.create(assignment=assignment, file=uploaded, original_name=uploaded.name)
        for item in self.request.data.get("items", []) if isinstance(self.request.data.get("items"), list) else []:
            AssignmentItem.objects.create(assignment=assignment, **item)


class SubmissionViewSet(viewsets.ModelViewSet):
    serializer_class = SubmissionSerializer
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_queryset(self):
        qs = Submission.objects.select_related("assignment", "student")
        user = self.request.user
        if user.is_admin:
            return qs
        if user.is_teaching_staff:
            return qs.filter(assignment__group__teacher=user)
        return qs.filter(student=user)

    def perform_create(self, serializer):
        submission = serializer.save(student=self.request.user, status=Submission.Status.SUBMITTED, submitted_at=timezone.now())
        for uploaded in self.request.FILES.getlist("files"):
            SubmissionFile.objects.create(submission=submission, file=uploaded, original_name=uploaded.name)

    @action(detail=True, methods=["post"], permission_classes=[IsStaffRole])
    def review(self, request, pk=None):
        submission = self.get_object()
        serializer = ReviewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("return_for_revision"):
            submission.status = Submission.Status.RETURNED
            submission.score = None
        else:
            submission.status = Submission.Status.GRADED
            submission.score = data["score"]
            submission.graded_at = timezone.now()
            submission.graded_by = request.user
        submission.feedback = data.get("feedback", "")
        submission.save()
        return Response(SubmissionSerializer(submission).data)


class TestViewSet(viewsets.ModelViewSet):
    serializer_class = TestSerializer
    permission_classes = [ReadOnlyOrStaff]
    filterset_fields = ["group", "is_published"]

    def get_queryset(self):
        qs = Test.objects.select_related("group").prefetch_related("questions")
        user = self.request.user
        if user.is_admin:
            return qs
        if user.is_teaching_staff:
            return qs.filter(group__teacher=user)
        return qs.filter(group__enrollments__student=user, is_published=True).distinct()

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        test = self.get_object()
        attempt, _ = TestAttempt.objects.get_or_create(test=test, student=request.user)
        if attempt.status == TestAttempt.Status.GRADED:
            return Response({"detail": "Тест уже пройден."}, status=400)
        attempt = grade_attempt(attempt, request.data.get("answers", {}))
        return Response(TestAttemptSerializer(attempt).data)


class QuestionViewSet(viewsets.ModelViewSet):
    serializer_class = QuestionSerializer
    permission_classes = [IsStaffRole]
    filterset_fields = ["test", "type"]
    queryset = Question.objects.select_related("test")


class TestAttemptViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = TestAttemptSerializer
    filterset_fields = ["test", "student", "status"]

    def get_queryset(self):
        qs = TestAttempt.objects.select_related("test", "student")
        user = self.request.user
        if user.is_admin:
            return qs
        if user.is_teaching_staff:
            return qs.filter(test__group__teacher=user)
        return qs.filter(student=user)


class ExerciseViewSet(viewsets.ModelViewSet):
    serializer_class = ExerciseSerializer
    permission_classes = [ReadOnlyOrStaff]
    filterset_fields = ["language", "type", "is_published"]
    search_fields = ["title"]
    queryset = Exercise.objects.select_related("language")

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=["post"])
    def attempt(self, request, pk=None):
        exercise = self.get_object()
        answers = request.data.get("answers", request.data)
        score = grade_exercise(exercise, answers)
        record = ExerciseAttempt.objects.create(
            exercise=exercise,
            student=request.user,
            answers=answers if isinstance(answers, dict) else {"value": answers},
            score=score,
        )
        return Response(ExerciseAttemptSerializer(record).data, status=status.HTTP_201_CREATED)


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdminRole]
    queryset = AuditLog.objects.select_related("actor")
    filterset_fields = ["action", "method"]
    search_fields = ["path", "actor__login", "actor__last_name"]


class NotificationViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = NotificationSerializer

    def get_queryset(self):
        return Notification.objects.filter(user=self.request.user)

    @action(detail=True, methods=["post"])
    def read(self, request, pk=None):
        item = self.get_object()
        item.is_read = True
        item.save(update_fields=["is_read"])
        return Response(NotificationSerializer(item).data)


class DashboardView(APIView):
    def get(self, request):
        user = request.user
        if user.is_admin:
            students = User.objects.filter(role=User.Role.STUDENT, is_active=True)
            teachers = User.objects.filter(role=User.Role.TEACHER, is_active=True)
            groups = Group.objects.filter(is_active=True)
            performance = group_performance()
            att_vals = [row["attendance"] for row in performance if row["attendance"]]
            avg_vals = [row["average"] for row in performance if row["average"]]
            ranked = sorted(performance, key=lambda row: row["average"], reverse=True)
            return Response(
                {
                    "role": user.role,
                    "kpis": {
                        "students": students.count(),
                        "teachers": teachers.count(),
                        "groups": groups.count(),
                        "attendance": round(sum(att_vals) / len(att_vals), 1) if att_vals else 0,
                        "average": round(sum(avg_vals) / len(avg_vals), 1) if avg_vals else 0,
                    },
                    "attendance_by_month": attendance_by_month(),
                    "group_performance": performance,
                    "best_groups": ranked[:3],
                    "risk_groups": list(reversed(ranked[-3:])) if ranked else [],
                }
            )
        if user.is_teaching_staff:
            groups = scoped_groups(user)
            pending = Submission.objects.filter(assignment__group__in=groups, status=Submission.Status.SUBMITTED).count()
            return Response(
                {
                    "role": user.role,
                    "groups": GroupSerializer(groups, many=True).data,
                    "pending_reviews": pending,
                }
            )
        groups = scoped_groups(user)
        progress = assignment_progress(user)
        tests_new = Test.objects.filter(group__in=groups, is_published=True).exclude(attempts__student=user).count()
        return Response(
            {
                "role": user.role,
                "groups": GroupSerializer(groups, many=True).data,
                "homework_pending": progress["pending"],
                "new_tests": tests_new,
                "average": average_score(user),
                "attendance": attendance_percent(user),
            }
        )


class TelegramWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        process_telegram_update(request.data)
        return Response({"ok": True})
