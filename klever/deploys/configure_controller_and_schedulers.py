#!/usr/bin/env python3
#
# Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
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

import json
import os

from klever.deploys.utils import get_logger, need_verifiercloud_scheduler, start_services, stop_services


def get_klever_addon_abs_path(deploy_dir, prev_deploy_info, name, verification_backend=False):
    klever_addon_desc = prev_deploy_info['Klever Addons']['Verification Backends'][name] \
        if verification_backend is True else prev_deploy_info['Klever Addons'][name]
    return os.path.abspath(os.path.join(deploy_dir, 'klever-addons',
                                        'verification-backends' if verification_backend else '',
                                        name, klever_addon_desc.get('executable path', '')))


def configure_task_and_job_configuration_paths(deploy_dir, prev_deploy_info, client_config):
    client_config['client']['addon binaries'] = []
    client_config['client']['addon python packages'] = []
    for key in (k for k in prev_deploy_info['Klever Addons'] if k != "Verification Backends"):
        client_config['client']['addon binaries'].append(get_klever_addon_abs_path(deploy_dir, prev_deploy_info, key))
    for key, addon_desc in ((k, d) for k, d in prev_deploy_info['Klever Addons'].items()
                            if k != "Verification Backends" and 'python path' in d):
        path = os.path.abspath(os.path.join('klever-addons', key, addon_desc['python path']))
        client_config['client']['addon python packages'].append(path)


def configure_controller_and_schedulers(logger, development, src_dir, deploy_dir, prev_deploy_info):
    logger.info('(Re)configure {0} Klever Controller and Klever schedulers'
                .format('development' if development else 'production'))

    services = ['klever-controller', 'klever-native-scheduler', 'klever-cgroup']
    if need_verifiercloud_scheduler(prev_deploy_info):
        services.append('klever-verifiercloud-scheduler')
    stop_services(logger, services)

    conf_dir = os.path.join(src_dir, 'klever', 'scheduler', 'conf')
    deploy_dir_abs = os.path.realpath(deploy_dir)

    logger.info('Configure Klever Controller')
    with open(os.path.join(conf_dir, 'controller.json')) as fp:
        controller_conf = json.load(fp)

    controller_conf['common']['working directory'] = os.path.join(deploy_dir_abs, 'klever-work/controller')

    controller_conf['Klever Bridge'].update({
        'user': 'service',
        'password': 'service'
    })

    controller_conf['client-controller']['consul'] = get_klever_addon_abs_path(deploy_dir, prev_deploy_info, 'Consul')

    with open(os.path.join(deploy_dir, 'klever-conf/controller.json'), 'w') as fp:
        json.dump(controller_conf, fp, sort_keys=True, indent=4)

    logger.info('Configure Klever Native Scheduler')
    with open(os.path.join(conf_dir, 'native-scheduler.json')) as fp:
        native_scheduler_conf = json.load(fp)

    native_scheduler_conf['common']['working directory'] = os.path.join(deploy_dir_abs,
                                                                        'klever-work/native-scheduler')
    if development:
        native_scheduler_conf['common']['keep working directory'] = True

    native_scheduler_conf['Klever Bridge'].update({
        'user': 'service',
        'password': 'service'
    })

    native_scheduler_conf['Klever jobs and tasks queue'].update({
        'username': 'service',
        'password': 'service'
    })

    native_scheduler_conf['scheduler'].update({
        'disable CPU cores account': True,
        'job client configuration': os.path.realpath(os.path.join(deploy_dir,
                                                                  'klever-conf/native-scheduler-job-client.json')),
        'task client configuration': os.path.realpath(os.path.join(deploy_dir,
                                                                   'klever-conf/native-scheduler-task-client.json'))
    })

    if development:
        native_scheduler_conf['scheduler']['keep working directory'] = True

    if 'KLEVER_NATIVESCHEDULER_CONCURRENT_JOBS' in os.environ:
        native_scheduler_conf['scheduler']['concurrent jobs'] = os.environ['KLEVER_NATIVESCHEDULER_CONCURRENT_JOBS']

    with open(os.path.join(deploy_dir, 'klever-conf/native-scheduler.json'), 'w') as fp:
        json.dump(native_scheduler_conf, fp, sort_keys=True, indent=4)

    logger.info('Configure Klever Native Scheduler Job Worker')

    with open(os.path.join(conf_dir, 'job-client.json')) as fp:
        job_client_conf = json.load(fp)

    configure_task_and_job_configuration_paths(deploy_dir, prev_deploy_info, job_client_conf)

    with open(os.path.join(deploy_dir, 'klever-conf/native-scheduler-job-client.json'), 'w') as fp:
        json.dump(job_client_conf, fp, sort_keys=True, indent=4)

    if need_verifiercloud_scheduler(prev_deploy_info):
        logger.info('Configure Klever VerifierCloud Scheduler')
        with open(os.path.join(conf_dir, 'verifiercloud-scheduler.json')) as fp:
            verifiercloud_scheduler_conf = json.load(fp)

        verifiercloud_scheduler_conf['common']['working directory'] = \
            os.path.join(deploy_dir_abs, 'klever-work/verifiercloud-scheduler')

        verifiercloud_scheduler_conf['Klever Bridge'].update({
            'user': 'service',
            'password': 'service'
        })

        verifiercloud_scheduler_conf['Klever jobs and tasks queue'].update({
            'username': 'service',
            'password': 'service'
        })

        verifiercloud_scheduler_conf['scheduler']['web client location'] =\
            get_klever_addon_abs_path(deploy_dir, prev_deploy_info, 'VerifierCloud Client')

        with open(os.path.join(deploy_dir, 'klever-conf/verifiercloud-scheduler.json'), 'w') as fp:
            json.dump(verifiercloud_scheduler_conf, fp, sort_keys=True, indent=4)

    logger.info('Configure Klever Native Scheduler Task Worker')

    with open(os.path.join(conf_dir, 'task-client.json')) as fp:
        task_client_conf = json.load(fp)

    configure_task_and_job_configuration_paths(deploy_dir, prev_deploy_info, task_client_conf)
    verification_backends = task_client_conf['client']['verification tools'] = {}
    for name, desc in prev_deploy_info['Klever Addons']['Verification Backends'].items():
        if desc['name'] not in verification_backends:
            verification_backends[desc['name']] = {}
        verification_backends[desc['name']][desc['version']] = \
            get_klever_addon_abs_path(deploy_dir, prev_deploy_info, name, verification_backend=True)

    with open(os.path.join(deploy_dir, 'klever-conf/native-scheduler-task-client.json'), 'w') as fp:
        json.dump(task_client_conf, fp, sort_keys=True, indent=4)

    start_services(logger, services)


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--development', default=False, action='store_true')
    parser.add_argument('--source-directory', default='klever')
    parser.add_argument('--deployment-directory', default='klever-inst')
    args = parser.parse_args()

    with open(os.path.join(args.deployment_directory, 'klever.json')) as fp:
        prev_deploy_info = json.load(fp)

    configure_controller_and_schedulers(get_logger(__name__), args.development, args.source_directory,
                                        args.deployment_directory,prev_deploy_info)


if __name__ == '__main__':
    main()
