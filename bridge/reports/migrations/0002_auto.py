# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-01-27 12:17
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportsafe',
            name='verifier_time',
            field=models.BigIntegerField(default=0),
            preserve_default=False
        ),
        migrations.AddField(
            model_name='reportunsafe',
            name='verifier_time',
            field=models.BigIntegerField(default=0),
            preserve_default=False
        ),
    ]
