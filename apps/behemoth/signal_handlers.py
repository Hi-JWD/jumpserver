from django.dispatch import receiver
from django.db.models.signals import pre_delete, post_save, post_delete

from common.signals import django_ready
from .libs.pools.worker import worker_pool
from .const import PlanCategory
from .models import Worker, Plan, Command


@receiver(django_ready)
def init_worker_pool(sender, **kwargs):
    try:
        workers = list(Worker.objects.all())
    except Exception: # noqa
        workers = []

    for w in workers:
        worker_pool.add_worker(w)


@receiver(pre_delete, sender=Plan)
def sync_plan_delete(sender, instance, **kwargs):
    if instance.category == PlanCategory.sync:
        relation_ids = instance.relations.values_list('id', flat=True)
        Command.objects.filter(relation_id__in=list(relation_ids)).delete()


@receiver([post_delete, post_save], sender=Worker)
def update_worker_pool(sender, instance, **kwargs):
    worker_pool.mark_worker_status(instance)
