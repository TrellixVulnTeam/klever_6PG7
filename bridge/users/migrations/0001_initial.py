# -*- coding: utf-8 -*-
# Generated by Django 1.10.4 on 2017-01-10 13:12
from __future__ import unicode_literals

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Extended',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('accuracy', models.SmallIntegerField(default=2)),
                ('data_format', models.CharField(choices=[('raw', 'Raw'), ('hum', 'Human-readable')], default='hum', max_length=3)),
                ('language', models.CharField(choices=[('en', 'English'), ('ru', 'Русский')], default='en', max_length=2)),
                ('role', models.CharField(choices=[('0', 'No access'), ('1', 'Producer'), ('2', 'Manager'), ('3', 'Expert'), ('4', 'Service user')], default='0', max_length=1)),
                ('timezone', models.CharField(default='Europe/Moscow', max_length=255)),
                ('assumptions', models.BooleanField(default=False)),
                ('triangles', models.BooleanField(default=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'user_extended',
            },
        ),
        migrations.CreateModel(
            name='Notifications',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('settings', models.CharField(max_length=255)),
                ('self_ntf', models.BooleanField(default=True)),
                ('user', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.CreateModel(
            name='PreferableView',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'user_preferable_view',
            },
        ),
        migrations.CreateModel(
            name='View',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('type', models.CharField(choices=[('1', 'job tree'), ('2', 'job view'), ('3', 'component children list'), ('4', 'unsafes list'), ('5', 'safes list'), ('6', 'unknowns list'), ('7', 'unsafe marks'), ('8', 'safe marks'), ('9', 'unknown marks')], default='1', max_length=1)),
                ('name', models.CharField(max_length=255)),
                ('view', models.TextField()),
                ('author', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'view',
            },
        ),
        migrations.AddField(
            model_name='preferableview',
            name='view',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='+', to='users.View'),
        ),
    ]
