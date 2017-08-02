# -*- coding: utf-8 -*-
# Generated by Django 1.9.5 on 2016-08-01 19:02
from __future__ import unicode_literals

from django.db import migrations, models


def remove_unsupported_jobs(apps, schema_editor):
    Job = apps.get_model('jobs', 'Job')

    # Collect all jobs of classes unsupported any more. These jobs will be removed later.
    jobs_to_be_removed = []
    for job in Job.objects.all():
        if job.type not in ('0', '3'):
            jobs_to_be_removed.append(job)

    # Remove trees of unsupported jobs starting from leaves.
    while True:
        if not jobs_to_be_removed:
            break

        for job in jobs_to_be_removed:
            job_to_be_removed = job

            for job_possible_child in jobs_to_be_removed:
                if job_possible_child.parent == job_to_be_removed:
                    job_to_be_removed = None
                    break

            if job_to_be_removed:
                job.delete()
                jobs_to_be_removed.remove(job_to_be_removed)
                break


class Migration(migrations.Migration):

    dependencies = [
        ('jobs', '0002_job_light'),
    ]

    operations = [
        migrations.AlterField(
            model_name='job',
            name='type',
            field=models.CharField(choices=[('0', 'Verification of Linux kernel modules'), ('3', 'Validation on commits in Linux kernel Git repositories')], default='0', max_length=1),
        ),
        migrations.RunPython(remove_unsupported_jobs)
    ]