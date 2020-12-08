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

import os
import re
import json
import copy
import hashlib
import importlib
import collections
import multiprocessing

import klever.core.components
import klever.core.utils
import klever.core.session

from klever.core.vtg.scheduling import Governer


@klever.core.components.before_callback
def __launch_sub_job_components(context):
    context.mqs['VTG common attrs'] = multiprocessing.Queue()

    # Queues used excusively in VTG
    context.mqs['program fragment desc files'] = multiprocessing.Queue()
    context.mqs['prepare'] = multiprocessing.Queue()

    # Queues shared by VRP
    context.mqs['pending tasks'] = multiprocessing.Queue()
    context.mqs['processing tasks'] = multiprocessing.Queue()
    context.mqs['processed'] = multiprocessing.Queue()


@klever.core.components.after_callback
def __prepare_descriptions_file(context):
    context.mqs['program fragment desc files'].put(
        os.path.relpath(context.PF_FILE, context.conf['main working directory']))


@klever.core.components.after_callback
def __submit_common_attrs(context):
    context.mqs['VTG common attrs'].put(context.common_attrs)


# Classes for queue transfer
Abstract = collections.namedtuple('AbstractTask', 'fragment rule_class')
Task = collections.namedtuple('Task', 'fragment rule_class envmodel rule workdir')

# Global values to be set once and used by other components running in parallel with the VTG
REQ_SPEC_CLASSES = None
FRAGMENT_DESC_FIELS = None
SINGLE_ENV_NAME = 'single'


class VTG(klever.core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(VTG, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                  separate_from_parent, include_child_resources)
        self.model_headers = {}
        self.req_spec_descs = []
        self.req_spec_classes = {}
        self.fragment_desc_files = {}

    def generate_verification_tasks(self):
        klever.core.utils.report(self.logger,
                                 'patch',
                                 {
                                   'identifier': self.id,
                                   'attrs': self.__get_common_attrs()
                                 },
                                 self.mqs['report files'],
                                 self.vals['report id'],
                                 self.conf['main working directory'])

        self.__extract_fragments_descs()
        self.__extract_req_spec_descs()
        self.__classify_req_spec_descs()

        # Set global shared values (read-only)
        global REQ_SPEC_CLASSES, FRAGMENT_DESC_FIELS
        REQ_SPEC_CLASSES = self.req_spec_classes
        FRAGMENT_DESC_FIELS = self.fragment_desc_files

        # Start plugins
        if not self.conf['keep intermediate files']:
            self.mqs['delete dir'] = multiprocessing.Queue()
        subcomponents = [('AAVTDG', self.__generate_all_abstract_verification_task_descs), VTGWL]
        self.launch_subcomponents(False, *subcomponents)

        self.clean_dir = True
        self.logger.info('Terminating the last queues')
        self.mqs['pending tasks'].put(None)

    main = generate_verification_tasks

    def __extract_template_plugin_descs(self, tmpl_descs):
        for tmpl_id, tmpl_desc in tmpl_descs.items():
            self.logger.info('Extract options for plugins of template "{0}"'.format(tmpl_id))

            if 'plugins' not in tmpl_desc:
                raise ValueError('Template "{0}" has not mandatory attribute "plugins"'.format(tmpl_id))

            for idx, plugin_desc in enumerate(tmpl_desc['plugins']):
                if not isinstance(plugin_desc, dict) or 'name' not in plugin_desc:
                    raise ValueError(
                        'Description of template "{0}" plugin "{1}" has incorrect format'.format(tmpl_id, idx))

            self.logger.debug(
                'Template "{0}" plugins are "{1}"'.format(tmpl_id,
                                                          [plugin_desc['name'] for plugin_desc in
                                                           tmpl_desc['plugins']]))

            # Get options for plugins specified in base template and merge them with the ones extracted above.
            if 'template' in tmpl_desc:
                if tmpl_desc['template'] not in tmpl_descs:
                    raise ValueError(
                        'Template "{0}" of template "{1}" could not be found in specifications base'
                            .format(tmpl_desc['template'], tmpl_id))

                self.logger.debug('Template "{0}" template is "{1}"'.format(tmpl_id, tmpl_desc['template']))

                for plugin_desc in tmpl_desc['plugins']:
                    for base_tmpl_plugin_desc in tmpl_descs[tmpl_desc['template']]['plugins']:
                        if plugin_desc['name'] == base_tmpl_plugin_desc['name']:
                            if 'options' in base_tmpl_plugin_desc:
                                if 'options' in plugin_desc:
                                    base_tmpl_plugin_opts = copy.deepcopy(base_tmpl_plugin_desc['options'])
                                    plugin_desc['options'] = klever.core.utils.merge_confs(
                                        base_tmpl_plugin_opts, plugin_desc['options'])
                                else:
                                    plugin_desc['options'] = base_tmpl_plugin_desc['options']
                            break

    # TODO: support inheritance of template sequences, i.e. when requirement needs template that is template of another one.
    def __extract_req_spec_descs(self):
        self.logger.info('Extract requirement specificaction decriptions')

        if 'specifications base' not in self.conf:
            raise KeyError('Nothing will be verified since specifications base is not specified')

        if 'requirement specifications' not in self.conf:
            raise KeyError('Nothing will be verified since requirement specifications to be checked are not specified')

        # Read specifications base.
        with open(self.conf['specifications base'], encoding='utf-8') as fp:
            raw_req_spec_descs = json.load(fp)

        if 'templates' not in raw_req_spec_descs:
            raise KeyError('Specifications base has not mandatory attribute "templates"')

        if 'requirement specifications' not in raw_req_spec_descs:
            raise KeyError('Specifications base has not mandatory attribute "requirement specifications"')

        tmpl_descs = raw_req_spec_descs['templates']
        self.__extract_template_plugin_descs(tmpl_descs)

        def exist_tmpl(tmpl_id, cur_req_id):
            if tmpl_id and tmpl_id not in tmpl_descs:
                raise KeyError('Template "{0}" for "{1}" is not described'.format(tmpl_id, cur_req_id))

        # Get identifiers, template identifiers and plugin options for all requirement specifications.
        def get_req_spec_descs(cur_req_spec_descs, cur_req_id, parent_tmpl_id):
            # Requirement specifications are described as a tree where leaves correspond to individual requirement
            # specifications while intermediate nodes hold common parts of requirement specification identifiers,
            # optional template identifiers and optional descriptions.
            # Handle sub-tree.
            if isinstance(cur_req_spec_descs, list):
                res_req_spec_descs = {}
                for idx, cur_req_spec_desc in enumerate(cur_req_spec_descs):
                    if 'identifier' not in cur_req_spec_desc:
                        raise KeyError('Identifier is not specified for {0} child of "{1}"'.format(idx, cur_req_id))

                    next_req_id = '{0}{1}'.format('{0}:'.format(cur_req_id) if cur_req_id else '',
                                                  cur_req_spec_desc['identifier'])

                    # Templates can be specified for requirement specification sub-trees and individual requirement
                    # specifications.
                    if 'template' in cur_req_spec_desc:
                        cur_tmpl_id = cur_req_spec_desc['template']
                        exist_tmpl(cur_tmpl_id, next_req_id)
                    else:
                        cur_tmpl_id = parent_tmpl_id

                    # Handle another one sub-tree.
                    if 'children' in cur_req_spec_desc:
                        res_req_spec_descs.update(get_req_spec_descs(cur_req_spec_desc['children'], next_req_id,
                                                                     cur_tmpl_id))
                    # Handle tree leaf.
                    else:
                        # Remove useless attributes.
                        for attr in ('identifier', 'description', 'template'):
                            if attr in cur_req_spec_desc:
                                del cur_req_spec_desc[attr]

                        if not cur_tmpl_id:
                            raise KeyError('Template is not specified for requirement "{0}"'.format(next_req_id))

                        cur_req_spec_desc['template'] = cur_tmpl_id
                        res_req_spec_descs[next_req_id] = cur_req_spec_desc

                return res_req_spec_descs
            # Handle tree root.
            else:
                # Template can be specified for all requirement specifications.
                root_tmpl_id = cur_req_spec_descs.get('template')
                exist_tmpl(root_tmpl_id, cur_req_id)
                if 'children' in cur_req_spec_descs:
                    return get_req_spec_descs(cur_req_spec_descs['children'], '', root_tmpl_id)
                else:
                    raise KeyError('Specifications base does not describe any requirement specifications')

        req_spec_descs = get_req_spec_descs(raw_req_spec_descs['requirement specifications'], '', None)

        # Get requirement specifications to be checked.
        check_req_spec_ids = set()
        matched_req_spec_id_patterns = set()
        for req_spec_id in req_spec_descs:
            for req_spec_id_pattern in self.conf['requirement specifications']:
                if re.search(r'^{0}$'.format(req_spec_id_pattern), req_spec_id):
                    matched_req_spec_id_patterns.add(req_spec_id_pattern)
                    check_req_spec_ids.add(req_spec_id)
                    break

        check_req_spec_ids = sorted(check_req_spec_ids)

        self.logger.debug('Following requirement specifications will be checked "{0}"'
                          .format(', '.join(check_req_spec_ids)))

        unmatched_req_spec_id_patterns = set(self.conf['requirement specifications']).difference(
            matched_req_spec_id_patterns)
        if unmatched_req_spec_id_patterns:
            raise ValueError('Following requirement specification identifier patters were not matched: "{0}"'
                             .format(', '.join(unmatched_req_spec_id_patterns)))

        # Complete descriptions of requirement specifications to be checked by adding plugin options specific for
        # requirement specifications to common template ones.
        for check_req_spec_id in check_req_spec_ids:
            check_req_spec_desc = req_spec_descs[check_req_spec_id]
            # Copy template plugin descriptions since we will overwrite them while the same template can be used by
            # different requirement specifications.
            tmpl_plugin_descs = copy.deepcopy(tmpl_descs[check_req_spec_desc['template']]['plugins'])

            check_req_spec_plugin_descs = []
            if 'plugins' in check_req_spec_desc:
                check_req_spec_plugin_descs = check_req_spec_desc['plugins']
                # Check requirement specification plugin descriptions.
                for idx, check_req_spec_plugin_desc in enumerate(check_req_spec_plugin_descs):
                    if 'name' not in check_req_spec_plugin_desc or 'options' not in check_req_spec_plugin_desc:
                        raise KeyError('Invalid description of {0} plugin of requirement specification "{1}"'
                                       .format(idx, check_req_spec_id))

            matched_req_spec_plugin_names = set()
            for tmpl_plugin_desc in tmpl_plugin_descs:
                # Template plugin description can miss specific options.
                if 'options' not in tmpl_plugin_desc:
                    tmpl_plugin_desc['options'] = {}

                for check_req_spec_plugin_desc in check_req_spec_plugin_descs:
                    if check_req_spec_plugin_desc['name'] == tmpl_plugin_desc['name']:
                        matched_req_spec_plugin_names.add(check_req_spec_plugin_desc['name'])
                        tmpl_plugin_desc['options'].update(check_req_spec_plugin_desc['options'])

            unmatched_req_spec_plugin_names = []
            for check_req_spec_plugin_desc in check_req_spec_plugin_descs:
                if check_req_spec_plugin_desc['name'] not in matched_req_spec_plugin_names:
                    unmatched_req_spec_plugin_names.append(check_req_spec_plugin_desc['name'])

            if unmatched_req_spec_plugin_names:
                raise KeyError('Following requirement specification plugins are not described within template: "{0}'
                               .format(', '.join(unmatched_req_spec_plugin_names)))

            # Add final description of requirements specification to be checked.
            self.req_spec_descs.append({
                'identifier': check_req_spec_id,
                'plugins': tmpl_plugin_descs
            })

        if self.conf['keep intermediate files']:
            self.logger.debug('Create file "{0}" with descriptions of requirement specifications to be checked'
                              .format('checked requirement specifications.json'))
            with open('checked requirement specifications.json', 'w', encoding='utf-8') as fp:
                json.dump(self.req_spec_descs, fp, ensure_ascii=False, sort_keys=True, indent=4)

    def __classify_req_spec_descs(self):
        # Determine requirement specification classes.
        for req_desc in self.req_spec_descs:
            hashes = dict()
            for plugin in (p for p in req_desc['plugins'] if p['name'] in ['SA', 'EMG']):
                hashes[plugin['name']] = plugin['options']

            if len(hashes) > 0:
                opt_cache = hashlib.sha224(str(hashes).encode('UTF8')).hexdigest()
                if opt_cache in self.req_spec_classes:
                    self.req_spec_classes[opt_cache].append(req_desc)
                else:
                    self.req_spec_classes[opt_cache] = [req_desc]
            else:
                self.req_spec_classes[req_desc['identifier']] = [req_desc]

        # Replace haches by rule names and convert lists to dictionary
        self.req_spec_classes = {rules[0]['identifier']: {r['identifier']: r for r in rules}
                                 for rules in self.req_spec_classes.values()}

        self.logger.info("Generated {} requirement classes from given descriptions".format(len(self.req_spec_classes)))

    def __gradual_submit(self, items_queue, quota):
        submitted = 0
        while 0 < quota and len(items_queue) > 0:
            quota -= 1
            submitted += 1
            element = items_queue.pop()
            task, *rest = element
            self.mqs['prepare'].put((type(task).__name__, tuple(task), *rest))
        if submitted > 0:
            self.logger.debug(f"Submitted {submitted} items")
        return submitted

    def __extract_fragments_descs(self):
        # Fetch fragment
        pf_file = self.mqs['program fragment desc files'].get()
        pf_file = os.path.join(self.conf['main working directory'], pf_file)
        self.mqs['program fragment desc files'].close()

        if os.path.isfile(pf_file):
            with open(pf_file, 'r', encoding='utf-8') as fp:
                program_fragment_descs = [pf_file.strip() for pf_file in fp.readlines()]
            if not self.conf['keep intermediate files']:
                os.remove(pf_file)
        else:
            raise FileNotFoundError

        # Fetch fragments and prepare initial tasks
        self.fragment_desc_files = {fragment: os.path.join(self.conf['main working directory'], file) for fragment, file
                                    in (i.split(':=') for i in program_fragment_descs)}
        self.logger.debug(f'Found descriptions of {len(program_fragment_descs)} fragments')

    def __get_abstract_tasks(self):
        for fragment in self.fragment_desc_files:
            if len(self.req_spec_descs) == 0:
                self.logger.warning(f'Program fragment {fragment} will not be verified since requirement specifications'
                                    ' are not specified')
            else:
                for rule_class in self.req_spec_classes:
                    task = Abstract(fragment, rule_class)
                    self.logger.debug(f'Create abstract task {task}')
                    yield task

    def __generate_all_abstract_verification_task_descs(self):
        # Statuses
        waiting = 0
        solving = 0
        prepare = list()
        atask_work_dirs = dict()
        atask_tasks = dict()

        max_tasks = int(self.conf['max solving tasks per sub-job'])
        keep_dirs = self.conf['keep intermediate files']

        self.logger.info('Generate all abstract verification task decriptions')
        governer = Governer(self.conf, self.logger, {})

        # Get abstract tasks from program fragment descriptions
        self.logger.info('Generate abstract tasks')
        for atask in self.__get_abstract_tasks():
            prepare.append((atask,))
        self.logger.info(f'There are {len(prepare)} abstract tasks in total')

        # Get the number of abstract tasks
        left_abstract_tasks = len(prepare)
        total_tasks = 0

        # Check that we can generate a variable number of environment models
        single_model = self.conf.get('single environment model per fragment', True)
        if single_model:
            total_tasks = len(self.fragment_desc_files) * len([1 for cl in self.req_spec_classes
                                              for rule in self.req_spec_classes[cl]])
            # Submit the number of tasks
            self.logger.info(f'Submit the total number of tasks expecting a single environment model per a fragment: {total_tasks}')
            self.mqs['total tasks'].put([self.conf['sub-job identifier'], total_tasks])
            governer.set_total_tasks(total_tasks)

        self.logger.info('Go to the main working loop for abstract tasks')
        while prepare or waiting or solving:
            self.logger.debug(f'Going to process {len(prepare)} tasks and abstract tasks and wait for {waiting}')

            # Submit more work to do
            quota = (max_tasks - waiting) if max_tasks > waiting else 0
            waiting += self.__gradual_submit(prepare, quota)

            # Get processed abstract tasks.
            new_items = klever.core.utils.get_waiting_first(self.mqs['processed'], timeout=3)
            for kind, desc, *other in new_items:
                waiting -= 1
                self.logger.debug(f'Received item {kind}')
                if kind == Abstract.__name__:
                    atask = Abstract(*desc)
                    aworkdir, models = other
                    left_abstract_tasks -= 1

                    if not keep_dirs:
                        atask_work_dirs[atask] = aworkdir
                        atask_tasks[atask] = set()

                    # Generate a verification task per a new environment model and rule
                    if models:
                        for env_model, workdir in models:
                            for rule in self.req_spec_classes[atask.rule_class]:
                                new_workdir = os.path.join(workdir, rule)
                                new = Task(atask.fragment, atask.rule_class, env_model, rule, new_workdir)
                                self.logger.debug(f'Create verification task {new}')
                                if not keep_dirs:
                                    atask_tasks[atask].add(new)

                                limitations = governer.resource_limitations(new)
                                prepare.append((new, limitations, 0))
                                if not single_model:
                                    total_tasks += 1
                    else:
                        self.logger.warning(f'There is no tasks generated for {atask}')
                        self.mqs['finished and failed tasks'].put((self.conf['sub-job identifier'], 'failed'))

                    if not single_model and left_abstract_tasks == 0:
                        # Submit the number of tasks
                        self.logger.info(f'Submit the total number of tasks: {total_tasks}')
                        self.mqs['total tasks'].put([self.conf['sub-job identifier'], total_tasks])
                        governer.set_total_tasks(total_tasks)
                    elif not single_model:
                        self.logger.debug(f'Wait for abstract tasks {left_abstract_tasks}')
                else:
                    task = Task(*desc)
                    atask = Abstract(task.fragment, task.rule_class)

                    # Check solution
                    accepted = True
                    if other:
                        solution_status = other.pop()
                        self.logger.info(f'Received solution for {task}')
                        status = 'finished'

                        accepted = governer.add_solution(task, solution_status)
                        if not accepted:
                            self.logger.info(f'Repeate solution for {task} later')
                    else:
                        self.logger.info(f'No solution received for {task}')
                        governer.add_solution(task)
                        status = 'failed'

                    if status == 'failed' or accepted:
                        # Send status to the progress watcher
                        self.mqs['finished and failed tasks'].put((self.conf['sub-job identifier'], status))

                        # Delete task working directory
                        if not self.conf['keep intermediate files']:
                            self.logger.debug(f'Delete task working directory {task.workdir}')
                            klever.core.utils.reliable_rmtree(self.logger, task.workdir)

                        # Delete abstract task working directory (with EMG dir)
                        if not keep_dirs:
                            atask_tasks[atask].remove(task)
                            if not atask_tasks[atask]:
                                self.logger.debug(f'Delete working directories related to {atask}: '
                                                  f'{atask_work_dirs[atask]}')
                                klever.core.utils.reliable_rmtree(self.logger, atask_work_dirs[atask])
                                del atask_tasks[atask]
                                del atask_work_dirs[atask]

                    # If there are tasks to schedule do this
                    if governer.rescheduling:
                        self.logger.info('We can repeate solution of timeouts now')
                        for _, task in governer.limitation_tasks:
                            if not governer.is_running(task):
                                attempt = governer.do_rescheduling(task)
                                if attempt:
                                    limitations = governer.resource_limitations(task)
                                    prepare.insert(0, (task, limitations, attempt))
                                else:
                                    # Add a solution and delete the task
                                    governer.add_solution(task)
                                    self.mqs['finished and failed tasks'].put((self.conf['sub-job identifier'], 'finished'))

        # Close the queue
        self.mqs['prepare'].put(None)
        self.mqs['processed'].close()

        self.logger.info("Stop generating verification tasks")

    def __get_common_attrs(self):
        self.logger.info('Get common atributes')
        common_attrs = self.mqs['VTG common attrs'].get()
        self.mqs['VTG common attrs'].close()
        return common_attrs


class VTGWL(klever.core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(VTGWL, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                    separate_from_parent, include_child_resources)
        global REQ_SPEC_CLASSES, FRAGMENT_DESC_FIELS
        self.fragment_desc_files = FRAGMENT_DESC_FIELS
        self.req_spec_classes = REQ_SPEC_CLASSES

    def task_generating_loop(self):
        number = klever.core.utils.get_parallel_threads_num(self.logger, self.conf, 'Tasks generation')

        self.logger.info("Start EMG workers")
        klever.core.components.launch_queue_workers(self.logger, self.mqs['prepare'],
                                                    self.factory, number, True)
        self.logger.info("Terminate VTGL worker")

    def factory(self, item):
        resource_limits = None
        rescheduling_attempt = None

        kind, args, *other = item
        if kind == Abstract.__name__:
            task = Abstract(*args)
            worker_class = EMGW
            identifier = "EMGW/{}/{}".format(task.fragment, task.rule_class)
            workdir = os.path.join(task.fragment, task.rule_class)
        else:
            task = Task(*args)
            resource_limits, rescheduling_attempt = other
            if rescheduling_attempt:
                worker_class = REPEAT
                identifier = "REPEAT/{}/{}/{}/{}/{}".format(task.fragment, task.rule_class, task.envmodel, task.rule,
                                                            rescheduling_attempt)
                workdir = os.path.join(task.workdir, f'{task.rule}/{rescheduling_attempt}')
            else:
                worker_class = PLUGINS
                identifier = "PLUGINS/{}/{}/{}/{}".format(task.fragment, task.rule_class, task.envmodel, task.rule)
                workdir = task.workdir
        self.logger.info(f'Create worker for {task}')
        return worker_class(self.conf, self.logger, self.parent_id, self.callbacks, self.mqs, self.vals, identifier,
                            workdir, [], True, req_spec_classes=self.req_spec_classes,
                            fragment_desc_files=self.fragment_desc_files, task=task, resource_limits=resource_limits,
                            rescheduling_attempt=rescheduling_attempt)

    main = task_generating_loop


class VTGW(klever.core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False, req_spec_classes=None,
                 fragment_desc_files=None, task=None, resource_limits=None, rescheduling_attempt=None):
        super(VTGW, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                   separate_from_parent, include_child_resources)
        self.initial_abstract_task_desc_file = 'initial abstract task.json'
        self.out_abstract_task_desc_file = 'abstract tasks.json'
        self.final_abstract_task_desc_file = 'final abstract task.json'
        self.prepared_data = tuple()
        self.send_data = True

        # Get tuple and convert it back
        self.task = task
        self.resource_limits = resource_limits
        self.req_spec_classes = req_spec_classes
        self.fragment_desc_files = fragment_desc_files
        self.rescheduling_attempt = rescheduling_attempt

        self.fragment_desc = self.__extract_fragment_desc(self.task.fragment)
        self.session = klever.core.session.Session(self.logger, self.conf['Klever Bridge'], self.conf['identifier'])

    def tasks_generator_worker(self):
        self._submit_attrs()
        self._generate_abstact_verification_task_desc()
        if not self.vals['task solving flag'].value:
            with self.vals['task solving flag'].get_lock():
                self.vals['task solving flag'].value = 1

    main = tasks_generator_worker

    def join(self, timeout=None, stopped=False):
        try:
            ret = super(VTGW, self).join(timeout, stopped)
        finally:
            if not self.is_alive() and self.send_data:
                prepared_data = self._get_prepared_data()
                if prepared_data:
                    self.logger.debug(f"Now send the data to the VTG for {self.task}")
                    self.mqs['processed'].put(prepared_data)
                else:
                    self.logger.debug(f"Skip sending any results for the {self.task}")

                # Send data only once
                self.send_data = False
        return ret

    def _generate_abstact_verification_task_desc(self):
        # Implement the method to do the workload
        pass

    def _get_prepared_data(self):
        self.logger.debug(f"There is no data has been prepared for {self.task}")
        return type(self.task).__name__, tuple(self.task)

    def _run_plugin(self, plugin_desc, initial_abstract_task_desc_file=None, out_abstract_task_desc_file=None):
        plugin_name = plugin_desc['name']
        plugin_work_dir = plugin_desc['name'].lower()
        plugin_conf = copy.deepcopy(self.conf)
        plugin_conf_file = f'{plugin_name.lower()} conf.json'
        initial_abstract_task_desc_file = initial_abstract_task_desc_file if initial_abstract_task_desc_file else \
            self.initial_abstract_task_desc_file
        out_abstract_task_desc_file = out_abstract_task_desc_file if out_abstract_task_desc_file else \
            self.out_abstract_task_desc_file

        self.logger.info(f'Launch plugin {plugin_name}')
        if 'options' in plugin_desc:
            plugin_conf.update(plugin_desc['options'])
        plugin_conf['in abstract task desc file'] = os.path.relpath(initial_abstract_task_desc_file,
                                                                    self.conf['main working directory'])
        plugin_conf['out abstract task desc file'] = os.path.relpath(out_abstract_task_desc_file,
                                                                     self.conf['main working directory'])
        # Get plugin configuration on the basis of common configuration, plugin options specific for requirement
        # specification and information on requirement itself. In addition put either initial or
        # current description of abstract verification task into plugin configuration.
        self.logger.debug(f'Put configuration of plugin "{plugin_name} to file {plugin_conf_file}')
        with open(plugin_conf_file, 'w', encoding='utf-8') as fp:
            klever.core.utils.json_dump(plugin_conf, fp, self.conf['keep intermediate files'])

        plugin = getattr(importlib.import_module(f'.{plugin_name.lower()}', 'klever.core.vtg'), plugin_name)
        p = plugin(plugin_conf, self.logger, self.id, self.callbacks, self.mqs, self.vals,
                   plugin_name, plugin_work_dir, separate_from_parent=True, include_child_resources=True)
        p.start()
        p.join()

    def _submit_task(self, plugin_desc, out_abstract_task_desc_file):
        plugin_work_dir = plugin_desc['name'].lower()
        self.logger.debug(f'Put final abstract verification task description to '
                          f'file "{self.final_abstract_task_desc_file}"')
        # Final abstract verification task description equals to abstract verification task description received
        # from last plugin.
        os.symlink(os.path.relpath(out_abstract_task_desc_file, os.path.curdir),
                   self.final_abstract_task_desc_file)

        # VTG will consume this abstract verification task description file.
        if os.path.isfile(os.path.join(plugin_work_dir, 'task.json')) and \
                os.path.isfile(os.path.join(plugin_work_dir, 'task files.zip')):
            task_id = self.session.schedule_task(os.path.join(plugin_work_dir, 'task.json'),
                                                 os.path.join(plugin_work_dir, 'task files.zip'))
            with open(out_abstract_task_desc_file, 'r', encoding='utf-8') as fp:
                final_task_data = json.load(fp)

            # Plan for checking status
            self.mqs['pending tasks'].put([
                [str(task_id), tuple(self.task), final_task_data["result processing"], self.fragment_desc,
                 final_task_data['verifier'], final_task_data['additional sources'],
                 final_task_data['verification task files']], self.rescheduling_attempt])

            self.logger.info("Submitted successfully verification task {} for solution".
                             format(os.path.join(plugin_work_dir, 'task.json')))
        else:
            self.logger.warning("There is no verification task generated by the last plugin, expect {}".
                                format(os.path.join(plugin_work_dir, 'task.json')))

    def _submit_attrs(self):
        files_list_files = []

        # Prepare program fragment description file
        files_list_file = 'files list.txt'
        klever.core.utils.save_program_fragment_description(self.fragment_desc, files_list_file)
        files_list_files.append(files_list_file)

        # Add attributes
        self.attrs.extend(
            [
                {
                    "name": "Program fragment",
                    "value": self.task.fragment,
                    "data": files_list_file,
                    "compare": True
                },
                {
                    "name": "Requirements specification class",
                    "value": self.task.rule_class
                }
            ]
        )

        # Send attributes to the Bridge
        klever.core.utils.report(
            self.logger,
            'patch',
            {
                'identifier': self.id,
                'attrs': self.attrs
            },
            self.mqs['report files'],
            self.vals['report id'],
            self.conf['main working directory'],
            data_files=files_list_files)

    def __extract_fragment_desc(self, fragment):
        program_fragment_desc_file = self.fragment_desc_files[fragment]
        with open(os.path.join(self.conf['main working directory'], program_fragment_desc_file),
                  encoding='utf-8') as fp:
            desc = json.load(fp)

        return desc


class EMGW(VTGW):

    def _get_prepared_data(self):
        pairs = []

        def create_task(task, model):
            task_workdir = os.path.join(self.work_dir, model)
            os.makedirs(task_workdir, exist_ok=True)
            task_file = os.path.join(task_workdir, self.initial_abstract_task_desc_file)
            with open(task_file, 'w', encoding='utf-8') as fp:
                klever.core.utils.json_dump(task, fp, self.conf['keep intermediate files'])
            pairs.append([model, task_workdir])

        # Send tasks to the VTG
        out_file = os.path.join(self.work_dir, self.out_abstract_task_desc_file)

        # Now read the final tasks
        self.logger.info(f'Read file with generated descriptions {out_file}')
        if os.path.isfile(out_file):
            with open(out_file, 'r', encoding="utf-8") as fp:
                tasks = json.load(fp)
            self.logger.info(f'Found {len(tasks)} generated tasks')
        else:
            self.logger.info(f'There is no environment models generated for {self.task}')
            tasks = []

        # Generate task descriptions for further tasks
        if len(tasks) == 1:
            env_model = SINGLE_ENV_NAME
            task_desc = tasks.pop()
            create_task(task_desc, env_model)
        else:
            for task_desc in tasks:
                env_model = task_desc["environment model identifier"]
                create_task(task_desc, env_model)

        # Submit new tasks to the VTG
        return type(self.task).__name__, tuple(self.task), self.work_dir, pairs

    def _generate_abstact_verification_task_desc(self):
        fragment = self.task.fragment
        rule_class = self.task.rule_class
        options = self.__get_pligin_conf(rule_class)

        self.logger.info(f"Start generating tasks for {fragment} and requirements specification {rule_class}")
        self.__prepare_initial_abstract_task(fragment, rule_class)

        # Here plugin will put modified abstract verification task description.
        try:
            self._run_plugin(options)
        except klever.core.components.ComponentError:
            self.logger.warning('EMG has failed')

    def __get_pligin_conf(self, rule_class):
        return next(iter(self.req_spec_classes[rule_class].values()))['plugins'][0]

    def __prepare_initial_abstract_task(self, fragment, rule_class):
        fragment_desc = self.fragment_desc

        # Initial abstract verification task looks like corresponding program fragment.
        initial_abstract_task_desc = copy.deepcopy(fragment_desc)
        initial_abstract_task_desc['id'] = '{0}/{1}'.format(fragment, rule_class)
        initial_abstract_task_desc['attrs'] = ()

        self.logger.debug(f'Put initial abstract verification task description to '
                          f'file {self.initial_abstract_task_desc_file}')
        with open(self.initial_abstract_task_desc_file, 'w', encoding='utf-8') as fp:
            klever.core.utils.json_dump(initial_abstract_task_desc, fp, self.conf['keep intermediate files'])


class PLUGINS(VTGW):

    def _submit_attrs(self):
        if self.task.envmodel != SINGLE_ENV_NAME:
            self.attrs.append(
                {
                    "name": "Environment model",
                    "value": self.task.envmodel,
                    "compare": True
                }
            )
        self.attrs.append(
            {
                "name": "Requirements specification",
                "value": self.task.rule,
                "compare": True
            }
        )
        super(PLUGINS, self)._submit_attrs()

    def _get_prepared_data(self):
        if os.path.isfile(os.path.join(self.work_dir, self.final_abstract_task_desc_file)):
            self.logger.debug(f"Task {self.task} is submitted to the VRP")
            return None
        else:
            self.logger.debug(f"Cannot find prepared verification task for {self.task}")
            return type(self.task).__name__, tuple(self.task)

    def _prepare_initial_task_desc(self):
        initial_abstract_task_desc_file = os.path.join(os.path.pardir, self.initial_abstract_task_desc_file)
        # Initial abstract verification task looks like corresponding program fragment.
        with open(initial_abstract_task_desc_file, 'r', encoding='utf-8') as fp:
            initial_abstract_task_desc = json.load(fp)
        initial_abstract_task_desc['id'] = '/'.join((self.task.fragment, self.task.rule_class, self.task.envmodel,
                                                     self.task.rule))
        self.logger.debug(f'Put initial abstract verification task description to'
                          f' {self.initial_abstract_task_desc_file}')
        with open(self.initial_abstract_task_desc_file, 'w', encoding='utf-8') as fp:
            klever.core.utils.json_dump(initial_abstract_task_desc, fp, self.conf['keep intermediate files'])

    def _get_plugins(self):
        return self.req_spec_classes[self.task.rule_class][self.task.rule]['plugins'][1:]

    def _generate_abstact_verification_task_desc(self):
        cur_abstract_task_desc_file = self.initial_abstract_task_desc_file
        out_abstract_task_desc_file = self.out_abstract_task_desc_file
        plugins = self._get_plugins()

        # Prepare initial task desc
        self.logger.info(f"Start generating tasks for {self.task}")
        self._prepare_initial_task_desc()

        # Invoke all plugins one by one.
        for plugin_desc in plugins:
            # Here plugin will put modified abstract verification task description.
            out_abstract_task_desc_file = '{0} abstract task.json'.format(plugin_desc['name'].lower())
            plugin_desc.get('options', {}).update({
                'solution class': self.task.rule,
                'override resource limits': self.resource_limits
            })

            try:
                self._run_plugin(plugin_desc, cur_abstract_task_desc_file, out_abstract_task_desc_file)
            except klever.core.components.ComponentError:
                self.logger.warning('Plugin {} failed'.format(plugin_desc['name']))
                break

            cur_abstract_task_desc_file = out_abstract_task_desc_file
        else:
            self._submit_task(plugin_desc, out_abstract_task_desc_file)


class REPEAT(PLUGINS):

    def _submit_attrs(self):
        self.attrs.append(
            {
                "name": "Rescheduling attempt",
                "value": str(self.rescheduling_attempt)
            }
        )
        super(REPEAT, self)._submit_attrs()

    def _get_plugins(self):
        return self.req_spec_classes[self.task.rule_class][self.task.rule]['plugins'][-1:]

    def _prepare_initial_task_desc(self):
        initial_abstract_task_desc_file = os.path.join(os.path.pardir, self.final_abstract_task_desc_file)
        plugin_desc = self.req_spec_classes[self.task.rule_class][self.task.rule]['plugins'][-1]

        self.logger.info(f"Prepare repeating solution of {self.task}")
        self.logger.info("Instead of running the {!r} plugin obtain results for the original run".
                         format(plugin_desc['name']))
        os.symlink(initial_abstract_task_desc_file, self.initial_abstract_task_desc_file)
