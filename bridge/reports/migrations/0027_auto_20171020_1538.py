# -*- coding: utf-8 -*-
# Generated by Django 1.11.3 on 2017-10-20 12:38
from __future__ import unicode_literals

from django.db import migrations, models
import reports.models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0026_remove_empty_cov'),
    ]

    operations = [
        migrations.AlterField(
            model_name='coveragearchive',
            name='archive',
            field=models.FileField(upload_to=reports.models.get_coverage_arch_dir),
        ),
    ]
