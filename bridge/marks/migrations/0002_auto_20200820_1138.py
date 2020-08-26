# Generated by Django 3.0.3 on 2020-08-20 08:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('marks', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='marksafereport',
            name='type',
            field=models.CharField(choices=[('0', 'Dissimilar'), ('1', 'Unconfirmed'), ('2', 'Automatic'), ('3', 'Confirmed')], default='0', max_length=1),
        ),
        migrations.AlterField(
            model_name='markunknownreport',
            name='type',
            field=models.CharField(choices=[('0', 'Dissimilar'), ('1', 'Unconfirmed'), ('2', 'Automatic'), ('3', 'Confirmed')], default='0', max_length=1),
        ),
        migrations.AlterField(
            model_name='markunsafereport',
            name='type',
            field=models.CharField(choices=[('0', 'Dissimilar'), ('1', 'Unconfirmed'), ('2', 'Automatic'), ('3', 'Confirmed')], default='0', max_length=1),
        ),
    ]
