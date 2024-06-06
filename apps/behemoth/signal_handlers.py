from django.dispatch import receiver
from django.db.models.signals import post_delete

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
