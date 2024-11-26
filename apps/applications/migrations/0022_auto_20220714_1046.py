# Generated by Django 3.2.12 on 2022-07-14 02:46

from django.db import migrations


def migrate_db_oracle_version_to_attrs(apps, schema_editor):
    db_alias = schema_editor.connection.alias
    model = apps.get_model("applications", "Application")
    oracles = list(model.objects.using(db_alias).filter(type='oracle'))
    for o in oracles:
        o.attrs['version'] = '12c'
    model.objects.using(db_alias).bulk_update(oracles, ['attrs'])


class Migration(migrations.Migration):
    dependencies = [
        ('applications', '0021_auto_20220629_1826'),
    ]

    operations = [
        migrations.RunPython(migrate_db_oracle_version_to_attrs)
    ]