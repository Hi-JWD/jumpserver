from django.dispatch import receiver
from django.db.models.signals import pre_delete, post_save, post_delete

from common.signals import django_ready
from .libs.pools.worker import worker_pool
from .const import PlanCategory, ExecutionCategory
from .models import Worker, Command, Execution


@receiver(django_ready)
def init_worker_pool(sender, **kwargs):
    try:
        workers = list(Worker.objects.all())
    except Exception: # noqa
        workers = []

    for w in workers:
        worker_pool.add_worker(w)


@receiver(pre_delete, sender=Execution)
def handle_execution_delete(sender, instance, **kwargs):
    if (instance.plan.category == PlanCategory.sync
            or instance.category == ExecutionCategory.pause):
        Command.objects.filter(execution_id=instance.id).delete()
    else:
        Command.objects.filter(execution_id=instance.id).update(has_delete=True)


@receiver([post_delete, post_save], sender=Worker)
def update_worker_pool(sender, instance, **kwargs):
    worker_pool.mark_worker_status(instance)
