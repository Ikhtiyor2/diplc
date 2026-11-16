from rest_framework import serializers

from apps.accounts.models import User
from apps.assessments.models import Question, Test, TestAttempt, TestSection
from apps.attendance.models import Attendance
from apps.groups.models import Enrollment, Group, Language
from apps.homework.models import Assignment, AssignmentFile, AssignmentItem, Submission, SubmissionFile
from apps.practice.models import Exercise, ExerciseAttempt
from apps.audit.models import AuditLog
from apps.notifications.models import Notification


class UserSerializer(serializers.ModelSerializer):
    full_name = serializers.CharField(read_only=True)
    initials = serializers.CharField(read_only=True)

    class Meta:
        model = User
        fields = [
            "id",
            "first_name",
            "last_name",
            "middle_name",
            "faculty",
            "course",
            "full_name",
            "initials",
            "login",
            "role",
            "telegram_id",
            "telegram_username",
            "phone",
            "is_active",
            "is_primary_admin",
            "created_at",
        ]
        read_only_fields = ["login", "telegram_id", "is_primary_admin", "created_at"]


class UserWriteSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=False)

    class Meta:
        model = User
        fields = ["id", "first_name", "last_name", "login", "role", "phone", "notes", "is_active", "password"]

    def create(self, validated):
        password = validated.pop("password", None)
        user = User(**validated)
        if password:
            user.set_password(password)
        else:
            user.set_unusable_password()
        user.save()
        return user

    def update(self, instance, validated):
        password = validated.pop("password", None)
        for key, value in validated.items():
            setattr(instance, key, value)
        if password:
            instance.set_password(password)
        instance.save()
        return instance


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = ["id", "code", "name", "native_name", "flag"]


class GroupSerializer(serializers.ModelSerializer):
    language = LanguageSerializer(read_only=True)
    language_id = serializers.PrimaryKeyRelatedField(
        source="language", queryset=Language.objects.all(), write_only=True
    )
    teacher = UserSerializer(read_only=True)
    teacher_id = serializers.PrimaryKeyRelatedField(
        source="teacher", queryset=User.objects.filter(role=User.Role.TEACHER), write_only=True, allow_null=True, required=False
    )
    students_count = serializers.IntegerField(source="enrollments.count", read_only=True)

    class Meta:
        model = Group
        fields = [
            "id",
            "name",
            "language",
            "language_id",
            "teacher",
            "teacher_id",
            "level",
            "schedule",
            "room",
            "is_active",
            "students_count",
            "created_at",
        ]


class EnrollmentSerializer(serializers.ModelSerializer):
    student = UserSerializer(read_only=True)
    student_id = serializers.PrimaryKeyRelatedField(
        source="student", queryset=User.objects.filter(role=User.Role.STUDENT), write_only=True
    )

    class Meta:
        model = Enrollment
        fields = ["id", "student", "student_id", "group", "attendance_percent", "joined_at"]


class AttendanceSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)

    class Meta:
        model = Attendance
        fields = ["id", "student", "student_name", "group", "lesson_date", "status", "comment", "created_at"]


class AssignmentFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssignmentFile
        fields = ["id", "file", "original_name", "uploaded_at"]


class AssignmentItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = AssignmentItem
        fields = ["id", "kind", "prompt", "exercise", "order"]


class AssignmentSerializer(serializers.ModelSerializer):
    files = AssignmentFileSerializer(many=True, read_only=True)
    items = AssignmentItemSerializer(many=True, read_only=True)
    group_name = serializers.CharField(source="group.name", read_only=True)

    class Meta:
        model = Assignment
        fields = [
            "id",
            "title",
            "description",
            "deadline",
            "group",
            "group_name",
            "created_by",
            "is_published",
            "files",
            "items",
            "created_at",
        ]
        read_only_fields = ["created_by"]


class SubmissionFileSerializer(serializers.ModelSerializer):
    class Meta:
        model = SubmissionFile
        fields = ["id", "file", "original_name", "uploaded_at"]


class SubmissionSerializer(serializers.ModelSerializer):
    files = SubmissionFileSerializer(many=True, read_only=True)
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    assignment_title = serializers.CharField(source="assignment.title", read_only=True)

    class Meta:
        model = Submission
        fields = [
            "id",
            "assignment",
            "assignment_title",
            "student",
            "student_name",
            "answer",
            "answers",
            "status",
            "score",
            "feedback",
            "files",
            "submitted_at",
            "graded_at",
        ]
        read_only_fields = ["student", "status", "score", "feedback", "submitted_at", "graded_at"]


class ReviewSerializer(serializers.Serializer):
    score = serializers.FloatField(min_value=0, max_value=100)
    feedback = serializers.CharField(allow_blank=True, required=False)
    return_for_revision = serializers.BooleanField(required=False, default=False)


class QuestionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Question
        fields = ["id", "test", "section", "type", "question_text", "payload", "points", "order"]


class TestSectionSerializer(serializers.ModelSerializer):
    class Meta:
        model = TestSection
        fields = ["id", "title", "kind", "body", "audio", "order"]


class TestSerializer(serializers.ModelSerializer):
    questions = QuestionSerializer(many=True, read_only=True)
    sections = TestSectionSerializer(many=True, read_only=True)
    questions_count = serializers.IntegerField(source="questions.count", read_only=True)

    class Meta:
        model = Test
        fields = [
            "id",
            "title",
            "description",
            "kind",
            "instructions",
            "group",
            "created_by",
            "time_limit_minutes",
            "is_published",
            "available_until",
            "sections",
            "questions",
            "questions_count",
            "created_at",
        ]
        read_only_fields = ["created_by"]


class TestAttemptSerializer(serializers.ModelSerializer):
    student_name = serializers.CharField(source="student.full_name", read_only=True)
    test_title = serializers.CharField(source="test.title", read_only=True)

    class Meta:
        model = TestAttempt
        fields = [
            "id",
            "student",
            "student_name",
            "test",
            "test_title",
            "answers",
            "score",
            "max_score",
            "status",
            "started_at",
            "submitted_at",
        ]


class ExerciseSerializer(serializers.ModelSerializer):
    language_name = serializers.CharField(source="language.name", read_only=True)

    class Meta:
        model = Exercise
        fields = [
            "id",
            "title",
            "language",
            "language_name",
            "type",
            "prompt",
            "content",
            "audio",
            "level",
            "is_published",
            "created_by",
            "created_at",
        ]
        read_only_fields = ["created_by"]


class ExerciseAttemptSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExerciseAttempt
        fields = ["id", "exercise", "student", "answers", "score", "completed_at"]
        read_only_fields = ["student", "score", "completed_at"]


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.CharField(source="actor.full_name", read_only=True)

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_name", "action", "method", "path", "metadata", "ip_address", "created_at"]


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "title", "body", "channel", "is_read", "created_at"]


class CredentialsSerializer(serializers.Serializer):
    first_name = serializers.CharField()
    last_name = serializers.CharField()
    role = serializers.ChoiceField(choices=User.Role.choices)
    phone = serializers.CharField(required=False, allow_blank=True)


class TokenObtainPairByLoginSerializer(serializers.Serializer):
    login = serializers.CharField()
    password = serializers.CharField()
