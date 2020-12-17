#
# Copyright (c) 2019 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

from django.core.management.base import BaseCommand, CommandError

from bridge.utils import logger
from jobs.preset import PopulatePresets
from marks.population import PopulateSafeMarks, PopulateUnsafeMarks, PopulateUnknownMarks, populate_tags
from service.population import populuate_schedulers


class Command(BaseCommand):
    help = 'Populates jobs, marks and tags.'
    requires_migrations_checks = True

    def add_arguments(self, parser):
        parser.add_argument('--all', dest='all', action='store_true', help='Populate everything?')
        parser.add_argument('--marks', dest='marks', action='store_true', help='Populate all marks?')
        parser.add_argument('--safe-marks', dest='marks_s', action='store_true', help='Populate safe marks?')
        parser.add_argument('--unsafe-marks', dest='marks_u', action='store_true', help='Populate unsafe marks?')
        parser.add_argument('--unknown-marks', dest='marks_f', action='store_true', help='Populate unknown marks?')
        parser.add_argument('--tags', dest='tags', action='store_true', help='Populate tags?')
        parser.add_argument('--schedulers', dest='schedulers', action='store_true', help='Populate schedulers?')
        parser.add_argument('--preset-jobs', dest='presets', action='store_true', help='Populate preset jobs?')

    def handle(self, *args, **options):
        # Preset jobs
        if options['all'] or options['presets']:
            self.stdout.write('Preset jobs population started')
            try:
                PopulatePresets().populate()
            except Exception as e:
                logger.exception(e)
                raise CommandError('Preset jobs population failed: %s' % e)
            self.stdout.write("Preset jobs were populated")

        # Tags
        if options['all'] or options['tags']:
            self.stdout.write('Tags population started')
            try:
                created, total = populate_tags()
            except Exception as e:
                logger.exception(e)
                raise CommandError('Tags population failed: %s' % e)
            self.stdout.write("{} of {} tags were populated".format(created, total))

        # Safe marks
        if options['all'] or options['marks'] or options['marks_s']:
            self.stdout.write('Safe marks population started')
            try:
                res = PopulateSafeMarks()
            except Exception as e:
                logger.exception(e)
                raise CommandError('Safe marks population failed: %s' % e)
            self.stdout.write("{} of {} safe marks were populated".format(res.created, res.total))

        # Unsafe marks
        if options['all'] or options['marks'] or options['marks_u']:
            self.stdout.write('Unsafe marks population started')
            try:
                res = PopulateUnsafeMarks()
            except Exception as e:
                logger.exception(e)
                raise CommandError('Unsafe marks population failed: %s' % e)
            self.stdout.write("{} of {} unsafe marks were populated".format(res.created, res.total))

        # Unknown marks
        if options['all'] or options['marks'] or options['marks_f']:
            self.stdout.write('Unknown marks population started')
            try:
                res = PopulateUnknownMarks()
            except Exception as e:
                logger.exception(e)
                raise CommandError('Unknown marks population failed: %s' % e)
            self.stdout.write("{} of {} unknown marks were populated".format(res.created, res.total))

        # Schedulers
        if options['all'] or options['schedulers']:
            populuate_schedulers()
            self.stdout.write('Schedulers were populated!')

        self.stdout.write('Population was successfully finished!')
