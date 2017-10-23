#
# Copyright (c) 2014-2016 ISPRAS (http://www.ispras.ru)
# Institute for System Programming of the Russian Academy of Sciences
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

import re
import importlib
import json
import multiprocessing
import queue
import os
import copy
import hashlib
import time
import shutil
import core.components
import core.utils
import core.session

@core.utils.before_callback
def __launch_sub_job_components(context):
    context.mqs['VTG common prj attrs'] = multiprocessing.Queue()
    context.mqs['pending tasks'] = multiprocessing.Queue()
    context.mqs['processed tasks'] = multiprocessing.Queue()
    context.mqs['prepared verification tasks'] = multiprocessing.Queue()
    context.mqs['prepare verification objects'] = multiprocessing.Queue()
    context.mqs['processing tasks'] = multiprocessing.Queue()
    context.mqs['verification obj desc files'] = multiprocessing.Queue()
    context.mqs['verification obj descs num'] = multiprocessing.Queue()
    context.mqs['shadow src tree'] = multiprocessing.Queue()
    context.mqs['model CC opts'] = multiprocessing.Queue()


@core.utils.after_callback
def __set_shadow_src_tree(context):
    context.mqs['shadow src tree'].put(context.shadow_src_tree)


@core.utils.after_callback
def __fixup_model_cc_opts(context):
    context.mqs['model CC opts'].put(context.model_cc_opts)


@core.utils.after_callback
def __generate_verification_obj_desc(context):
    if context.verification_obj_desc:
        context.mqs['verification obj desc files'].put(
            os.path.relpath(context.verification_obj_desc_file, context.conf['main working directory']))


@core.utils.after_callback
def __generate_all_verification_obj_descs(context):
    context.logger.info('Terminate verification object description files message queue')
    context.mqs['verification obj desc files'].put(None)
    # todo: fix or rewrite
    #context.mqs['verification obj descs num'].put(context.verification_obj_desc_num)


@core.utils.after_callback
def __set_common_prj_attrs(context):
    context.mqs['VTG common prj attrs'].put(context.common_prj_attrs)


def _extract_plugin_descs(logger, tmpl_id, tmpl_desc):
    logger.info('Extract descriptions for plugins of template "{0}"'.format(tmpl_id))

    if 'plugins' not in tmpl_desc:
        raise ValueError(
            'Template "{0}" has not mandatory attribute "plugins"'.format(tmpl_id))

    # Copy plugin descriptions since we will overwrite them while the same template can be used by different rule
    # specifications
    plugin_descs = copy.deepcopy(tmpl_desc['plugins'])

    for idx, plugin_desc in enumerate(plugin_descs):
        if isinstance(plugin_desc, dict) \
                and (len(plugin_desc.keys()) > 1 or not isinstance(list(plugin_desc.keys())[0], str)) \
                and not isinstance(plugin_desc, str):
            raise ValueError(
                'Description of template "{0}" plugin "{1}" has incorrect format'.format(tmpl_id, idx))
        if isinstance(plugin_desc, dict):
            plugin_descs[idx] = {
                'name': list(plugin_desc.keys())[0],
                'options': plugin_desc[list(plugin_desc.keys())[0]]
            }
        else:
            plugin_descs[idx] = {'name': plugin_desc}

    logger.debug(
        'Template "{0}" plugins are "{1}"'.format(tmpl_id, [plugin_desc['name'] for plugin_desc in plugin_descs]))

    return plugin_descs


def _extract_rule_spec_desc(logger, raw_rule_spec_descs, rule_spec_id):
    logger.info('Extract description for rule specification "{0}"'.format(rule_spec_id))

    # Get raw rule specification description.
    if rule_spec_id in raw_rule_spec_descs['rule specifications']:
        rule_spec_desc = raw_rule_spec_descs['rule specifications'][rule_spec_id]
    else:
        raise ValueError(
            'Specified rule specification "{0}" could not be found in rule specifications DB'.format(rule_spec_id))

    # Get rid of useless information.
    for attr in ('description',):
        if attr in rule_spec_desc:
            del (rule_spec_desc[attr])

    # Get rule specification template which it is based on.
    if 'template' not in rule_spec_desc:
        raise ValueError(
            'Rule specification "{0}" has not mandatory attribute "template"'.format(rule_spec_id))
    tmpl_id = rule_spec_desc['template']
    # This information won't be used any more.
    del (rule_spec_desc['template'])
    logger.debug('Rule specification "{0}" template is "{1}"'.format(rule_spec_id, tmpl_id))
    if 'templates' not in raw_rule_spec_descs or tmpl_id not in raw_rule_spec_descs['templates']:
        raise ValueError(
            'Template "{0}" of rule specification "{1}" could not be found in rule specifications DB'.format(
                tmpl_id, rule_spec_id))
    tmpl_desc = raw_rule_spec_descs['templates'][tmpl_id]

    # Get options for plugins specified in template.
    plugin_descs = _extract_plugin_descs(logger, tmpl_id, tmpl_desc)

    # Get options for plugins specified in base template and merge them with the ones extracted above.
    if 'template' in tmpl_desc:
        if tmpl_desc['template'] not in raw_rule_spec_descs['templates']:
            raise ValueError('Template "{0}" of template "{1}" could not be found in rule specifications DB'.format(
                tmpl_desc['template'], tmpl_id))

        logger.debug('Template "{0}" template is "{1}"'.format(tmpl_id, tmpl_desc['template']))

        base_tmpl_plugin_descs = _extract_plugin_descs(logger, tmpl_desc['template'],
                                                       raw_rule_spec_descs['templates'][tmpl_desc['template']])

        for plugin_desc in plugin_descs:
            for base_tmpl_plugin_desc in base_tmpl_plugin_descs:
                if plugin_desc['name'] == base_tmpl_plugin_desc['name']:
                    if 'options' in base_tmpl_plugin_desc:
                        if 'options' in plugin_desc:
                            plugin_desc['options'] = core.utils.merge_confs(base_tmpl_plugin_desc['options'],
                                                                            plugin_desc['options'])
                        else:
                            plugin_desc['options'] = base_tmpl_plugin_desc['options']

    # Add plugin options specific for rule specification.
    rule_spec_plugin_names = []
    # Names of all remained attributes are considered as plugin names, values - as corresponding plugin options.
    for attr in rule_spec_desc:
        plugin_name = attr
        rule_spec_plugin_names.append(plugin_name)
        is_plugin_specified = False

        for plugin_desc in plugin_descs:
            if plugin_name == plugin_desc['name']:
                is_plugin_specified = True
                if 'options' not in plugin_desc:
                    plugin_desc['options'] = {}
                plugin_desc['options'].update(rule_spec_desc[plugin_name])
                logger.debug(
                    'Plugin "{0}" options specific for rule specification "{1}" are "{2}"'.format(
                        plugin_name, rule_spec_id, rule_spec_desc[plugin_name]))
                break

        if not is_plugin_specified:
            raise ValueError(
                'Rule specification "{0}" plugin "{1}" is not specified in template "{2}"'.format(
                    rule_spec_id, plugin_name, tmpl_id))

    # We don't need to keep plugin options specific for rule specification in such the form any more.
    for plugin_name in rule_spec_plugin_names:
        del (rule_spec_desc[plugin_name])

    rule_spec_desc['plugins'] = plugin_descs

    # Add rule specification identifier to its description after all. Do this so late to avoid treating of "id" as
    # plugin name above.
    rule_spec_desc['id'] = rule_spec_id

    return rule_spec_desc


# This function is invoked to collect plugin callbacks.
def _extract_rule_spec_descs(conf, logger):
    logger.info('Extract rule specificaction decriptions')

    if 'rule specifications DB' not in conf:
        logger.warning('Nothing will be verified since rule specifications DB is not specified')
        return []

    if 'rule specifications' not in conf:
        logger.warning('Nothing will be verified since rule specifications are not specified')
        return []

    if 'specifications set' not in conf:
        logger.warning('Nothing will be verified since specifications set is not specified')
        return []

    # Read rule specification descriptions DB.
    with open(core.utils.find_file_or_dir(logger, conf['main working directory'], conf['rule specifications DB']),
              encoding='utf8') as fp:
        raw_rule_spec_descs = json.load(fp)

    if 'rule specifications' not in raw_rule_spec_descs:
        raise KeyError('Rule specifications DB has not mandatory attribute "rule specifications"')

    if 'all' in conf['rule specifications']:
        if not len(conf['rule specifications']) == 1:
            raise ValueError(
                'You can not specify "all" rule specifications together with some other rule specifications')

        # Add all rule specification identifiers from DB.
        conf['rule specifications'] = sorted(raw_rule_spec_descs['rule specifications'].keys())

        # Remove all empty rule specifications since they are intended for development.
        rule_specs = []
        for rule_spec_id in conf['rule specifications']:
            if rule_spec_id.find('empty') == -1 and rule_spec_id.find('test') == -1:
                rule_specs.append(rule_spec_id)
        conf['rule specifications'] = rule_specs
        logger.debug('Following rule specifications will be checked "{0}"'.format(conf['rule specifications']))

    rule_spec_descs = []

    for rule_spec_id in conf['rule specifications']:
        rule_spec_descs.append(_extract_rule_spec_desc(logger, raw_rule_spec_descs, rule_spec_id))

    if conf['keep intermediate files']:
        if os.path.isfile('rule spec descs.json'):
            raise FileExistsError('Rule specification descriptions file "rule spec descs.json" already exists')
        logger.debug('Create rule specification descriptions file "rule spec descs.json"')
        with open('rule spec descs.json', 'w', encoding='utf8') as fp:
            json.dump(rule_spec_descs, fp, ensure_ascii=False, sort_keys=True, indent=4)

    return rule_spec_descs


def _classify_rule_descriptions(logger, rule_descriptions):
    # Determine rule classes
    rule_classes = {}
    for rule_spec_desc in rule_descriptions:
        hashes = dict()
        for plugin in (p for p in rule_spec_desc['plugins'] if p['name'] in ['SA', 'EMG']):
            hashes[plugin['name']] = plugin['options']

        if len(hashes) > 0:
            opt_cache = hashlib.sha224(str(hashes).encode('UTF8')).hexdigest()
            if opt_cache in rule_classes:
                rule_classes[opt_cache].append(rule_spec_desc)
            else:
                rule_classes[opt_cache] = [rule_spec_desc]
        else:
            rule_classes[rule_spec_desc['name']] = [rule_spec_desc]
    logger.info("Generated {} rule classes from given descriptions".format(len(rule_classes)))
    return rule_classes


_rule_spec_descs = None
_rule_spec_classes = None


@core.utils.propogate_callbacks
def collect_plugin_callbacks(conf, logger):
    logger.info('Get VTG plugin callbacks')

    global _rule_spec_descs, _rule_spec_classes
    _rule_spec_descs = _extract_rule_spec_descs(conf, logger)
    _rule_spec_classes = _classify_rule_descriptions(logger, _rule_spec_descs)
    plugins = []

    # Find appropriate classes for plugins if so.
    for rule_spec_desc in _rule_spec_descs:
        for plugin_desc in rule_spec_desc['plugins']:
            try:
                plugin = getattr(importlib.import_module('.{0}'.format(plugin_desc['name'].lower()), 'core.vtg'),
                                 plugin_desc['name'])
                # Remember found class to create its instance during main operation.
                plugin_desc['plugin'] = plugin
                if plugin not in plugins:
                    plugins.append(plugin)
            except ImportError:
                raise NotImplementedError('Plugin {0} is not supported'.format(plugin_desc['name']))

    return core.utils.get_component_callbacks(logger, plugins, conf)


def resolve_rule_class(name):
    rc = [identifier for identifier in _rule_spec_classes if name in
          [r['id'] for r in _rule_spec_classes[identifier]]][0]
    return rc


class VTG(core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, locks, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(VTG, self).__init__(conf, logger, parent_id, callbacks, mqs, locks, vals, id, work_dir, attrs,
                                  separate_from_parent, include_child_resources)
        self.model_headers = {}
        self.rule_spec_descs = None

    def generate_verification_tasks(self):
        self.rule_spec_descs = _rule_spec_descs
        self.set_model_headers()
        self.__get_shadow_src_tree()
        self.__get_model_cc_opts()

        core.utils.report(self.logger,
                          'attrs',
                          {
                              'id': self.id,
                              'attrs': self.__get_common_prj_attrs()
                          },
                          self.mqs['report files'],
                          self.vals['report id'],
                          self.conf['main working directory'])

        # Start plugins
        subcomponents = [('AAVTDG', self.__generate_all_abstract_verification_task_descs)]
        for i in range(core.utils.get_parallel_threads_num(self.logger, self.conf, 'Tasks generation')):
            subcomponents.append(VTGWL)
        self.launch_subcomponents(*subcomponents)

        self.mqs['pending tasks'].put(None)
        self.mqs['pending tasks'].close()

    main = generate_verification_tasks

    def set_model_headers(self):
        """Set model headers. Do not rename function - it has a callback in LKBCE."""
        self.logger.info('Set model headers')

        for rule_spec_desc in self.rule_spec_descs:
            self.logger.debug('Set headers of rule specification "{0}"'.format(rule_spec_desc['id']))
            for plugin_desc in rule_spec_desc['plugins']:
                if plugin_desc['name'] != 'RSG':
                    continue

                for models in ('common models', 'models'):
                    if models in plugin_desc['options']:
                        for model_c_file, model in plugin_desc['options'][models].items():
                            if 'headers' not in model:
                                continue

                            self.logger.debug('Set headers of model with C file "{0}"'.format(model_c_file))

                            if isinstance(model['headers'], dict):
                                # Find out base specifications set.
                                base_specs_set = None
                                for specs_set in model['headers']:
                                    if re.search(r'\(base\)', specs_set):
                                        base_specs_set = specs_set
                                        break
                                if not base_specs_set:
                                    raise KeyError('Could not find base specifications set')

                                # Always require all headers of base specifications set.
                                headers = model['headers'][base_specs_set]

                                specs_set = self.conf['specifications set']

                                # Add/exclude specific headers of specific specifications set.
                                if specs_set != base_specs_set and specs_set in model['headers']:
                                    if 'add' in model['headers'][specs_set]:
                                        for add_header in model['headers'][specs_set]['add']:
                                            headers.append(add_header)
                                    if 'exclude' in model['headers'][specs_set]:
                                        for exclude_header in model['headers'][specs_set]['exclude']:
                                            headers.remove(exclude_header)
                            else:
                                headers = model['headers']

                            self.model_headers[model_c_file] = headers

                            self.logger.debug('Set headers "{0}"'.format(headers))

    def __get_shadow_src_tree(self):
        self.logger.info('Get shadow source tree')

        self.conf['shadow source tree'] = self.mqs['shadow src tree'].get()

        self.mqs['shadow src tree'].close()

        self.logger.debug('Shadow source tree "{0}"'.format(self.conf['shadow source tree']))

    def __get_model_cc_opts(self):
        self.logger.info('Get model CC options')

        self.conf['model CC opts'] = self.mqs['model CC opts'].get()

        self.mqs['model CC opts'].close()

    def __generate_all_abstract_verification_task_descs(self):
        def get_from_queue_no_wait(collection, name):
            s = True
            try:
                while True:
                    element = self.mqs[name].get_nowait()
                    if element is None:
                        self.logger.debug('Message queue {!r} was terminated'.format(name))
                        self.mqs[name].close()
                        s = False
                        break
                    collection.append(element)
            except queue.Empty:
                pass

            return s

        self.logger.info('Generate all abstract verification task decriptions')
        vo_descriptions = dict()
        processing_status = dict()
        initial = dict()

        max_tasks = int(self.conf['max solving tasks per sub-job'])
        active_tasks = 0
        expect_objects = True
        while True:
            # Fetch pilot statuses
            pilot_statuses = []
            # This queue will not inform about the end of tasks generation
            get_from_queue_no_wait(pilot_statuses, 'prepared verification tasks')
            # Process them
            for status in pilot_statuses:
                vobject, rule_name = status
                self.logger.info("Pilot verificatio task for {!r} and rule name {!r} is prepared".
                                 format(vobject, rule_name))
                rule_class = resolve_rule_class(rule_name)

                if vobject in processing_status and rule_class in processing_status[vobject] and \
                                rule_name in processing_status[vobject][rule_class]:
                    processing_status[vobject][rule_class][rule_name] = False

            # Fetch solutions
            solutions = []
            # This queue will not inform about the end of tasks generation
            get_from_queue_no_wait(solutions, 'processed tasks')

            # Process them
            for solution in solutions:
                vobject, rule_name = solution
                self.logger.info("Verificatio task for {!r} and rule name {!r} is either finished or failed".
                                 format(vobject, rule_name))
                rule_class = resolve_rule_class(rule_name)
                processing_status[vobject][rule_class][rule_name] = True
                active_tasks -= 1

            # Fetch object
            if expect_objects:
                verification_obj_desc_files = []
                expect_objects = get_from_queue_no_wait(verification_obj_desc_files, 'verification obj desc files')

                for verification_obj_desc_file in verification_obj_desc_files:
                    with open(os.path.join(self.conf['main working directory'], verification_obj_desc_file),
                              encoding='utf8') as fp:
                        verification_obj_desc = json.load(fp)
                    vo_descriptions[verification_obj_desc['id']] = verification_obj_desc
                    initial[verification_obj_desc['id']] = list(_rule_spec_classes.keys())

                    if not self.rule_spec_descs:
                        self.logger.warning('Verification object {0} will not be verified since rule specifications'
                                            ' are not specified'.format(verification_obj_desc['id']))

            # Submit initial objects
            for vo in list(initial.keys()):
                while len(initial[vo]) > 0:
                    if active_tasks < max_tasks:
                        rule_class = initial[vo].pop()
                        vobject = vo_descriptions[vo]
                        rule_name = _rule_spec_classes[rule_class][0]['id']
                        self.logger.info("Prepare initial verification tasks for {!r} and rule {!r}".
                                         format(vo, rule_name))
                        self.mqs['prepare verification objects'].put((vobject, _rule_spec_classes[rule_class][0]))

                        # Set status
                        if vo not in processing_status:
                            processing_status[vo] = {}
                        processing_status[vo][rule_class] = {rule_name: None}
                        active_tasks += 1
                    else:
                        break
                else:
                    self.logger.info("Trggered all initial tasks for verification object {!r}".format(vo))
                    del initial[vo]

            # Check statuses
            for vobject in list(processing_status.keys()):
                for rule_class in list(processing_status[vobject].keys()):
                    # Check readiness for further tasks generation
                    pilot_task_status = processing_status[vobject][rule_class][_rule_spec_classes[rule_class][0]['id']]
                    if (pilot_task_status is False or pilot_task_status is True) and active_tasks < max_tasks:
                        for rule in [rule for rule in _rule_spec_classes[rule_class][1:] if
                                     rule['id'] not in processing_status[vobject][rule_class]]:
                            if active_tasks < max_tasks:
                                self.logger.info("Submit next verification task after having cached plugin results for "
                                                 "verification object {!r} and rule {!r}".format(vobject, rule['id']))
                                self.mqs['prepare verification objects'].put(
                                    (vo_descriptions[vobject], rule))
                                processing_status[vobject][rule_class][rule['id']] = None
                                active_tasks += 1
                            else:
                                break

                    solved = 0
                    for rule in _rule_spec_classes[rule_class]:
                        if rule['id'] in processing_status[vobject][rule_class] and \
                                processing_status[vobject][rule_class][rule['id']]:
                            solved += 1

                    if solved == len(_rule_spec_classes[rule_class]):
                        if not self.conf['keep intermediate files']:
                            for rule in processing_status[vobject][rule_class]:
                                shutil.rmtree(os.path.join(vobject, rule))
                        del processing_status[vobject][rule_class]

                if len(processing_status[vobject]) == 0:
                    self.logger.info("All tasks for verification object {!r} are either solved or failed".
                                     format(vobject))
                    # Verification object is lastly processed
                    del processing_status[vobject]
                    del vo_descriptions[vobject]

            if not expect_objects and active_tasks == 0 and len(vo_descriptions) == 0 and len(initial) == 0:
                for _ in range(core.utils.get_parallel_threads_num(self.logger, self.conf, 'Tasks generation')):
                    self.mqs['prepare verification objects'].put(None)
                self.mqs['prepared verification tasks'].close()
                break
            else:
                self.logger.debug("There are {} initial tasks to be generated, {} active tasks, {} verification object "
                                  "descriptions and expectation verification tasks flag is {}".
                                  format(len(initial), active_tasks, len(vo_descriptions), expect_objects))

            time.sleep(3)

        self.logger.info("Stop generating verification tasks")

    def __get_common_prj_attrs(self):
        self.logger.info('Get common project atributes')

        common_prj_attrs = self.mqs['VTG common prj attrs'].get()

        self.mqs['VTG common prj attrs'].close()

        return common_prj_attrs


class VTGWL(core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, locks, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(VTGWL, self).__init__(conf, logger, parent_id, callbacks, mqs, locks, vals, id, work_dir, attrs,
                                    separate_from_parent, include_child_resources)
        # Required for a callback
        self.verification_object = None
        self.rule_specification = None

    def task_generating_loop(self):
        self.logger.info("Start VTGL worker")
        while True:
            pair = self.mqs['prepare verification objects'].get()
            if pair is None:
                self.mqs['prepare verification objects'].close()
                break
            vo = pair[0]
            rs = pair[1]
            self.logger.debug("VTGL is about to start VTGW for {!r}, {!r}".format(vo['id'], rs['id']))
            try:
                obj = VTGW(self.conf, self.logger, self.parent_id, self.callbacks, self.mqs,
                           self.locks, self.vals,"{}/{}/VTGW".format(vo['id'], rs['id']), os.path.join(vo['id'], rs['id']),
                           attrs=[{"Rule specification": rs['id']}, {"Verification object": vo['id']}],
                           separate_from_parent=True, verification_object=vo, rule_spec=rs)
                obj.start()
                obj.join()
            except core.components.ComponentError:
                self.logger.warning("Failed to generate verification task for {!r} and {!r}".format(vo, rs))

        self.logger.info("Terminate VTGL worker")

    main = task_generating_loop


class VTGW(core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, locks, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False, verification_object=None, rule_spec=None):
        super(VTGW, self).__init__(conf, logger, parent_id, callbacks, mqs, locks, vals, id, work_dir, attrs,
                                   separate_from_parent, include_child_resources)
        self.verification_object = verification_object
        self.rule_specification = rule_spec
        self.abstract_task_desc_file = None
        self.session = core.session.Session(self.logger, self.conf['Klever Bridge'], self.conf['identifier'])

    def tasks_generator_worker(self):
        try:
            self.generate_abstact_verification_task_desc(self.verification_object, self.rule_specification)
        except Exception:
            self.plugin_fail_processing()

    main = tasks_generator_worker

    def generate_abstact_verification_task_desc(self, verification_obj_desc, rule_spec_desc):
        """Has a callback!"""
        # todo: fix or reimplement
        # Count the number of generated abstract verification task descriptions.
        # self.abstract_task_desc_num += 1
        self.logger.info("Start generating tasks for verification object {!r} and rule specification {!r}".
                         format(verification_obj_desc['id'], rule_spec_desc['id']))
        self.verification_object = verification_obj_desc['id']
        self.rule_specification = rule_spec_desc['id']

        # todo: fix or reimplement
        # self.logger.info(
        #     'Generate abstract verification task description for {0} ({1}{2})'.format(
        #         'verification object "{0}" and rule specification "{1}"'.format(*initial_attr_vals),
        #         self.abstract_task_desc_num, '/{0}'.format(self.abstract_task_descs_num.value)
        #         if self.abstract_task_descs_num.value else ''))

        # Prepare pilot workdirs if it will be possible to reuse data
        rule_class = resolve_rule_class(rule_spec_desc['id'])
        pilot_rule = _rule_spec_classes[rule_class][0]['id']
        pilot_plugins_work_dir = os.path.join(os.path.pardir, pilot_rule)

        # Initial abstract verification task looks like corresponding verification object.
        initial_abstract_task_desc = copy.deepcopy(verification_obj_desc)
        initial_abstract_task_desc['id'] = '{0}/{1}'.format(self.verification_object, self.rule_specification)
        initial_abstract_task_desc['attrs'] = ()
        for grp in initial_abstract_task_desc['grps']:
            grp['cc extra full desc files'] = []
            for cc_full_desc_file in grp['cc full desc files']:
                with open(os.path.join(self.conf['main working directory'], cc_full_desc_file),
                          encoding='utf8') as fh:
                    command = json.load(fh)
                in_file = command['in files'][0]
                grp['cc extra full desc files'].append(
                    {'cc full desc file': cc_full_desc_file, "in file": in_file})
            del (grp['cc full desc files'])
        initial_abstract_task_desc_file = 'initial abstract task.json'
        self.logger.debug(
            'Put initial abstract verification task description to file "{0}"'.format(
                initial_abstract_task_desc_file))
        with open(initial_abstract_task_desc_file, 'w', encoding='utf8') as fp:
            json.dump(initial_abstract_task_desc, fp, ensure_ascii=False, sort_keys=True, indent=4)

        # Invoke all plugins one by one.
        cur_abstract_task_desc_file = initial_abstract_task_desc_file
        out_abstract_task_desc_file = None
        for plugin_desc in rule_spec_desc['plugins']:
            # Here plugin will put modified abstract verification task description.
            plugin_work_dir = plugin_desc['name'].lower()
            out_abstract_task_desc_file = '{0} abstract task.json'.format(plugin_desc['name'].lower())

            if rule_spec_desc['id'] not in [c[0]['id'] for c in _rule_spec_classes.values()] and \
                    plugin_desc['name'] in ['SA', 'EMG']:
                # Expect that there is a work directory which has all prepared
                # Make symlinks to the pilot rule work dir
                self.logger.info("Instead of running the {!r} plugin for the {!r} rule lets use already obtained "
                                 "results for the {!r} rule".format(plugin_desc['name'], self.rule_specification, pilot_rule))
                pilot_plugin_work_dir = os.path.join(pilot_plugins_work_dir, plugin_desc['name'].lower())
                pilot_abstract_task_desc_file = os.path.join(
                    pilot_plugins_work_dir, '{0} abstract task.json'.format(plugin_desc['name'].lower()))
                os.symlink(os.path.relpath(pilot_abstract_task_desc_file, os.path.curdir), out_abstract_task_desc_file)
                os.symlink(os.path.relpath(pilot_plugin_work_dir, os.path.curdir), plugin_work_dir)
            else:
                self.logger.info('Launch plugin {0}'.format(plugin_desc['name']))

                # Get plugin configuration on the basis of common configuration, plugin options specific for rule
                # specification and information on rule specification itself. In addition put either initial or current
                # description of abstract verification task into plugin configuration.
                plugin_conf = copy.deepcopy(self.conf)
                if 'options' in plugin_desc:
                    plugin_conf.update(plugin_desc['options'])
                if 'bug kinds' in rule_spec_desc:
                    plugin_conf.update({'bug kinds': rule_spec_desc['bug kinds']})
                plugin_conf['in abstract task desc file'] = os.path.relpath(cur_abstract_task_desc_file,
                                                                            self.conf[
                                                                                'main working directory'])
                plugin_conf['out abstract task desc file'] = os.path.relpath(out_abstract_task_desc_file,
                                                                             self.conf[
                                                                                 'main working directory'])

                plugin_conf_file = '{0} conf.json'.format(plugin_desc['name'].lower())
                self.logger.debug(
                    'Put configuration of plugin "{0}" to file "{1}"'.format(plugin_desc['name'],
                                                                             plugin_conf_file))
                with open(plugin_conf_file, 'w', encoding='utf8') as fp:
                    json.dump(plugin_conf, fp, ensure_ascii=False, sort_keys=True, indent=4)

                try:
                    p = plugin_desc['plugin'](plugin_conf, self.logger, self.id, self.callbacks, self.mqs,
                                              self.locks, self.vals, plugin_desc['name'],
                                              plugin_work_dir, separate_from_parent=True,
                                              include_child_resources=True)
                    p.start()
                    p.join()
                except core.components.ComponentError:
                    self.plugin_fail_processing()
                    break

                if self.rule_specification in [c[0]['id'] for c in _rule_spec_classes.values()] and \
                        plugin_desc['name']  == 'EMG':
                    self.logger.debug("Signal to VTG that the cache preapred for the rule {!r} is ready for the "
                                      "further use".format(pilot_rule))
                    self.mqs['prepared verification tasks'].put((self.verification_object, self.rule_specification))

            cur_abstract_task_desc_file = out_abstract_task_desc_file
        else:
            final_abstract_task_desc_file = 'final abstract task.json'
            self.logger.debug(
                'Put final abstract verification task description to file "{0}"'.format(
                    final_abstract_task_desc_file))
            # Final abstract verification task description equals to abstract verification task description received
            # from last plugin.
            os.symlink(os.path.relpath(out_abstract_task_desc_file, os.path.curdir),
                       final_abstract_task_desc_file)

            # VTG will consume this abstract verification task description file.
            self.abstract_task_desc_file = out_abstract_task_desc_file
            shadow_src_dir = os.path.abspath(os.path.join(self.conf['main working directory'],
                                                          self.conf['shadow source tree']))

            task_id = self.session.schedule_task(os.path.join(plugin_work_dir, 'task.json'),
                                                 os.path.join(plugin_work_dir, 'task files.zip'))
            with open(self.abstract_task_desc_file, 'r', encoding='utf8') as fp:
                final_task_data = json.load(fp)

            # Plan for checking staus
            self.mqs['pending tasks'].put([str(task_id),
                                           final_task_data["result processing"],
                                           self.verification_object,
                                           self.rule_specification,
                                           final_task_data['verifier'],
                                           shadow_src_dir])

    def plugin_fail_processing(self):
        """The function has a callback in sub-job processing!"""
        self.logger.debug("VTGW that processed {!r}, {!r} failed".
                          format(self.verification_object, self.rule_specification))
        self.mqs['processed tasks'].put((self.verification_object, self.rule_specification))

