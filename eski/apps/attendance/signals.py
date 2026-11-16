from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from apps.core.metrics import attendance_percent

from .models import Attendance


def refresh_enrollment(student_id: int, group_id: int) -> None:
    from apps.groups.models import Enrollment

    enrollment = Enrollment.objects.filter(student_id=student_id, group_id=group_id).first()
    if not enrollment:
        return
    enrollment.attendance_percent = attendance_percent(enrollment.student, enrollment.group)
    enrollment.save(update_fields=["attendance_percent"])


@receiver(post_save, sender=Attendance)
def attendance_saved(sender, instance, **kwargs):
    refresh_enrollment(instance.student_id, instance.group_id)


@receiver(post_delete, sender=Attendance)
def attendance_deleted(sender, instance, **kwargs):
    refresh_enrollment(instance.student_id, instance.group_id)
