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

import argparse
import json
import hashlib
import multiprocessing
import os
import pkg_resources
import shutil
import time
import traceback
import queue

import klever.core.job
import klever.core.session
import klever.core.utils
import klever.core.components


class Core(klever.core.components.CallbacksCaller):
    DEFAULT_CONF_FILE = 'core.json'
    ID = '/'

    def __init__(self):
        self.exit_code = 0
        self.start_time = 0
        self.conf = {}
        self.is_solving_file = None
        self.is_solving_file_fp = None
        self.logger = None
        self.comp = []
        self.session = None
        self.mqs = {}
        self.report_id = multiprocessing.Value('i', 1)
        self.uploading_reports_process = None
        self.uploading_reports_process_exitcode = multiprocessing.Value('i', 0)
        self.callbacks = {}
        self.is_start_report_uploaded = False

    def main(self):
        try:
            # Remember approximate time of start to count wall time.
            self.start_time = time.time()

            self.get_conf()

            self.prepare_work_dir()
            self.change_work_dir()

            self.logger = klever.core.utils.get_logger(type(self).__name__, self.conf['logging'])
            self.logger.info('Solve job "{0}"'.format(self.conf['identifier']))

            self.session = klever.core.session.Session(self.logger, self.conf['Klever Bridge'], self.conf['identifier'])
            self.session.start_job_decision(klever.core.job.JOB_FORMAT, klever.core.job.JOB_ARCHIVE)

            self.mqs['report files'] = multiprocessing.Manager().Queue()

            os.makedirs('child resources'.encode('utf-8'))

            self.uploading_reports_process = Reporter(self.conf, self.logger, self.ID, self.callbacks, self.mqs,
                                                      {'report id': self.report_id})
            self.uploading_reports_process.start()

            self.get_comp_desc()
            klever.core.utils.report(
                self.logger,
                'start',
                {
                    'identifier': self.ID,
                    'parent': None,
                    'component': type(self).__name__,
                    'attrs': [{
                        'name': 'Klever version',
                        'value': pkg_resources.get_distribution('klever').version
                    }],
                    'computer': self.comp
                },
                self.mqs['report files'],
                self.report_id,
                self.conf['main working directory']
            )
            self.is_start_report_uploaded = True

            klever.core.job.start_jobs(self, {
                'report id': self.report_id,
                'coverage_finished': multiprocessing.Manager().dict()
            })
        except Exception:
            self.process_exception()

            if self.mqs:
                try:
                    with open('problem desc.txt', 'a', encoding='utf-8') as fp:
                        if fp.tell():
                            fp.write('\n')
                        traceback.print_exc(file=fp)

                    if self.is_start_report_uploaded:
                        klever.core.utils.report(
                            self.logger,
                            'unknown',
                            {
                                'identifier': self.ID + '/',
                                'parent': self.ID,
                                'problem_description': klever.core.utils.ArchiveFiles(['problem desc.txt'])
                            },
                            self.mqs['report files'],
                            self.report_id,
                            self.conf['main working directory']
                        )
                except Exception:
                    self.process_exception()
        finally:
            try:
                if self.mqs:
                    self.logger.info('Terminate report files message queue')
                    self.mqs['report files'].put(None)

                    if self.uploading_reports_process.is_alive():
                        self.logger.info('Wait for uploading all reports except Core finish report')
                        self.uploading_reports_process.join()

                    # Create Core finish report just after other reports are uploaded. Otherwise time between creating
                    # Core finish report and finishing uploading all reports won't be included into wall time of Core.
                    child_resources = klever.core.components.all_child_resources()
                    report = {'identifier': self.ID}
                    report.update(klever.core.components.count_consumed_resources(
                        self.logger, self.start_time, child_resources=child_resources))

                    if os.path.isfile('log.txt'):
                        report['log'] = klever.core.utils.ArchiveFiles(['log.txt'])

                    klever.core.utils.report(self.logger, 'finish', report, self.mqs['report files'], self.report_id,
                                             self.conf['main working directory'])

                    self.logger.info('Terminate report files message queue')
                    self.mqs['report files'].put(None)

                    # Do not try to upload Core finish report if uploading of other reports already failed.
                    if not self.uploading_reports_process.exitcode:
                        self.uploading_reports_process = Reporter(self.conf, self.logger, self.ID, self.callbacks,
                                                                  self.mqs, {'report id': self.report_id})
                        self.uploading_reports_process.start()
                        self.logger.info('Wait for uploading Core finish report')
                        self.uploading_reports_process.join()

                    # Do not override exit code of main program with the one of auxiliary process uploading reports.
                    if not self.exit_code:
                        self.exit_code = self.uploading_reports_process.exitcode
            except Exception:
                self.process_exception()

                # Do not upload reports and wait for corresponding process any more if something else went wrong above.
                if self.uploading_reports_process.is_alive():
                    self.uploading_reports_process.terminate()
            # At least release working directory even if cleaning code above raised some exceptions.
            finally:
                if self.is_solving_file_fp and not self.is_solving_file_fp.closed:
                    if self.logger:
                        self.logger.info('Release working directory')
                    os.remove(self.is_solving_file)

                # Remove the whole working directory after all if needed.
                if self.conf and not self.conf['keep intermediate files']:
                    shutil.rmtree(os.path.abspath('.'))

                if self.logger:
                    self.logger.info('Exit with code "{0}"'.format(self.exit_code))

                return self.exit_code

    def get_conf(self):
        # Get configuration file from command-line options. If it is not specified, then use the default one.
        parser = argparse.ArgumentParser(description='Main script of Klever Core.')
        parser.add_argument('conf file', nargs='?', default=self.DEFAULT_CONF_FILE,
                            help='configuration file (default: {0})'.format(self.DEFAULT_CONF_FILE))
        conf_file = vars(parser.parse_args())['conf file']

        # Read configuration from file.
        with open(conf_file, encoding='utf-8') as fp:
            self.conf = json.load(fp)

    def prepare_work_dir(self):
        """
        Clean up and create the working directory. Prevent simultaneous usage of the same working directory.
        """
        # This file exists during Klever Core occupies working directory.
        self.is_solving_file = os.path.join(self.conf['working directory'], 'is solving')

        def check_another_instance():
            if not self.conf['ignore other instances'] and os.path.isfile(self.is_solving_file):
                raise FileExistsError('Another instance of Klever Core occupies working directory "{0}"'.format(
                    self.conf['working directory']))

        check_another_instance()

        # Remove (if exists) and create (if doesn't exist) working directory.
        # Note, that shutil.rmtree() doesn't allow to ignore files as required by specification. So, we have to:
        # - remove the whole working directory (if exists),
        # - create working directory (pass if it is created by another Klever Core),
        # - test one more time whether another Klever Core occupies the same working directory,
        # - occupy working directory.
        shutil.rmtree(self.conf['working directory'], True)

        os.makedirs(self.conf['working directory'].encode('utf-8'), exist_ok=True)

        check_another_instance()

        # Occupy working directory until the end of operation.
        # Yes there may be race condition, but it won't be.
        self.is_solving_file_fp = open(self.is_solving_file, 'w', encoding='utf-8')

        # Create directory where all reports and report files archives will be actually written to.
        os.mkdir(os.path.join(self.conf['working directory'], 'reports'))

    def change_work_dir(self):
        # Change working directory forever.
        # We can use path for "is solving" file relative to future working directory since exceptions aren't raised when
        # we have relative path but don't change working directory yet.
        self.is_solving_file = os.path.relpath(self.is_solving_file, self.conf['working directory'])
        os.chdir(self.conf['working directory'])

        self.conf['main working directory'] = os.path.abspath(os.path.curdir)

    def get_comp_desc(self):
        self.logger.info('Get computer description')

        entities = tuple([
            {entity_name_cmd[0]: klever.core.utils.get_entity_val(self.logger, entity_name_cmd[0], entity_name_cmd[1])}
            for entity_name_cmd in (
                ('node name', 'uname -n'),
                ('CPU model', 'cat /proc/cpuinfo | grep -m1 "model name" | sed -r "s/^.*: //"'),
                ('number of CPU cores', 'cat /proc/cpuinfo | grep processor | wc -l'),
                ('memory size', 'cat /proc/meminfo | grep "MemTotal" | sed -r "s/^.*: *([0-9]+).*/1024 * \\1/" | bc'),
                ('Linux kernel version', 'uname -r'),
                ('host architecture', 'uname -m'),
            )
            ])

        # Add computer description to configuration since it can be used by (sub)components.
        for entity in entities:
            self.conf.update(entity)

        # Represent memory size for users more pretty.
        entities[3]['memory size'] = '{0} GB'.format(int(entities[3]['memory size'] / 10 ** 9))

        self.comp = {
            'identifier': hashlib.sha224(json.dumps(entities).encode('utf-8')).hexdigest(),
            'display': entities[0]['node name'],
            'data': entities[1:]
        }

    def process_exception(self):
        self.exit_code = 1

        if self.logger:
            self.logger.exception('Catch exception')
        else:
            traceback.print_exc()


class Reporter(klever.core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(Reporter, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                       separate_from_parent, include_child_resources)

    def send_reports(self):
        session = klever.core.session.Session(self.logger, self.conf['Klever Bridge'], self.conf['identifier'])
        issleep = True
        while True:
            # Report batches of reports each 3 seconds. This reduces the number of requests quite considerably.
            if issleep:
                time.sleep(3)
            else:
                issleep = True

            reports_and_report_file_archives = []
            is_finish = False
            while True:
                try:
                    # TODO: replace MQ with "reports and report file archives".
                    report_and_report_file_archives = self.mqs['report files'].get_nowait()

                    if report_and_report_file_archives is None:
                        self.logger.debug('Report files message queue was terminated')
                        is_finish = True
                        break

                    reports_and_report_file_archives.append(report_and_report_file_archives)

                    # Do not send more than 10 reports at once. Otherwise different strange issues may appear im Core
                    # and Bridge.
                    if len(reports_and_report_file_archives) == 10:
                        # Do not sleep since there may be pending reports already.
                        issleep = False
                        break
                except queue.Empty:
                    break

            if reports_and_report_file_archives:
                for report_and_report_file_archives in reports_and_report_file_archives:
                    report_file_archives = report_and_report_file_archives.get('report file archives')
                    self.logger.debug('Upload report file "{0}"{1}'.format(
                        report_and_report_file_archives['report file'],
                        ' with report file archives:\n{0}'
                        .format('\n'.join(['  {0}'.format(archive) for archive in report_file_archives]))
                        if report_file_archives else ''))

                session.upload_reports_and_report_file_archives(reports_and_report_file_archives)

                # Remove reports and report file archives if needed.
                if not self.conf['keep intermediate files']:
                    for report_and_report_file_archives in reports_and_report_file_archives:
                        os.remove(report_and_report_file_archives['report file'])
                        report_file_archives = report_and_report_file_archives.get('report file archives')
                        if report_file_archives:
                            for archive in report_file_archives:
                                os.remove(archive)

            if is_finish:
                break

    main = send_reports
