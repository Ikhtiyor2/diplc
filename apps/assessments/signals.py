from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.notifications.services import notify_test_graded, notify_test_published

from .models import Test, TestAttempt


@receiver(post_save, sender=Test)
def test_saved(sender, instance, created, **kwargs):
    if created and instance.is_published:
        notify_test_published(instance)


@receiver(post_save, sender=TestAttempt)
def attempt_saved(sender, instance, **kwargs):
    if instance.status == TestAttempt.Status.GRADED:
        notify_test_graded(instance)
