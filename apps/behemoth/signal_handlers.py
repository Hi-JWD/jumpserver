from django.dispatch import receiver
from django.db.models.signals import post_delete, post_save

from common.signals import django_ready
from .libs.pools.worker import worker_pool
from .models import Worker, Plan, Command, Execution


@receiver(django_ready)
def init_worker_pool(sender, **kwargs):
    for w in Worker.objects.all():
        worker_pool.add_worker(w)


@receiver(post_delete, sender=Plan)
def on_plan_delete(sender, instance, **kwargs):
    execution = Execution.objects.filter(plan_id=instance.id).first()
    if execution:
        execution.delete()
        Command.objects.filter(execution_id=execution.id).delete()


@receiver(post_delete, sender=Worker)
def on_worker_delete(sender, instance, **kwargs):
    worker_pool.delete_worker(instance)


@receiver(post_save, sender=Worker)
def on_worker_add(sender, instance, created, **kwargs):
    if not created:
        worker_pool.refresh_worker(instance)
    else:
        worker_pool.add_worker(instance)
