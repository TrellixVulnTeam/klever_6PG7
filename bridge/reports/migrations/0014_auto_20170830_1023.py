# -*- coding: utf-8 -*-
# Generated by Django 1.10.2 on 2017-08-30 10:23
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [('reports', '0013_clear_comparison_cache')]

    operations = [
        migrations.AlterField(
            model_name='component', name='name',
            field=models.CharField(db_index=True, max_length=20, unique=True),
        ),
    ]
