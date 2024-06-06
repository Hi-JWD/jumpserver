from rest_framework import serializers
from django.utils.translation import gettext as _

from ..models import Iteration


class IterationSerializer(serializers.ModelSerializer):

    class Meta:
        model = Iteration
        fields_mini = ['id', 'name']
        fields_small = fields_mini
        fields = fields_small
