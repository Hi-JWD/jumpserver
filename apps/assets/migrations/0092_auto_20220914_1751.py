# Generated by Django 3.2.14 on 2022-09-14 09:51

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('assets', '0091_auto_20220629_1826'),
    ]

    operations = [
        migrations.AddField(
            model_name='authbook',
            name='allow_change_auth',
            field=models.BooleanField(default=True, verbose_name='Allow change auth'),
        ),
        migrations.AddField(
            model_name='historicalauthbook',
            name='allow_change_auth',
            field=models.BooleanField(default=True, verbose_name='Allow change auth'),
        ),
    ]
