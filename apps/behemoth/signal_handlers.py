from django.dispatch import receiver
from django.db.models.signals import post_delete, pre_save, post_save
from django.core.exceptions import ObjectDoesNotExist

from common.signals import django_ready
from .libs.pools.worker import worker_pool
from .models import Worker, Plan, Command, Execution


@receiver(django_ready)
def init_worker_pool(sender, **kwargs):
    try:
        workers = list(Worker.objects.all())
    except Exception: # noqa
        workers = []

    for w in workers:
        worker_pool.add_worker(w)


@receiver(post_delete, sender=Plan)
def on_plan_delete(sender, instance, **kwargs):
    execution = Execution.objects.filter(plan_id=instance.id).first()
    if execution:
        Command.objects.filter(execution_id=execution.id).delete()
        execution.delete()


@receiver(post_delete, sender=Worker)
def on_worker_delete(sender, instance, **kwargs):
    worker_pool.delete_worker(instance)


@receiver(pre_save, sender=Worker)
def on_worker_add_pre(sender, instance, **kwargs):
    try:
        worker_pool.delete_worker(instance.worker)
    except ObjectDoesNotExist:
        pass


@receiver(post_save, sender=Worker)
def on_worker_add(sender, instance, created, **kwargs):
    worker_pool.add_worker(instance)
