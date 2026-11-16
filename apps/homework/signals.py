from datetime import timedelta

from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.notifications.services import notify_homework_graded, notify_homework_published, notify_submission_received

from .models import Assignment, Submission


@receiver(post_save, sender=Assignment)
def assignment_saved(sender, instance, created, **kwargs):
    if created and instance.is_published:
        notify_homework_published(instance)


@receiver(post_save, sender=Submission)
def submission_saved(sender, instance, created, **kwargs):
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not created:
        lock_fields = {"reviewing_by", "reviewing_at"}
        if set(update_fields) <= lock_fields:
            return
    if instance.status == Submission.Status.SUBMITTED and instance.submitted_at:
        if timezone.now() - instance.submitted_at < timedelta(seconds=15):
            notify_submission_received(instance)
    if instance.status == Submission.Status.GRADED and instance.graded_at:
        if timezone.now() - instance.graded_at < timedelta(seconds=15):
            notify_homework_graded(instance)
