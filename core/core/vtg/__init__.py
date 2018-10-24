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

import re
import importlib
import json
import multiprocessing
import os
import copy
import hashlib
import time
import core.components
import core.utils
import core.session

from core.vtg.scheduling import Balancer
import clade.interface as clade_api


@core.components.before_callback
def __launch_sub_job_components(context):
    context.mqs['VTG common prj attrs'] = multiprocessing.Queue()
    context.mqs['pending tasks'] = multiprocessing.Queue()
    context.mqs['processed tasks'] = multiprocessing.Queue()
    context.mqs['prepared verification tasks'] = multiprocessing.Queue()
    context.mqs['prepare verification objects'] = multiprocessing.Queue()
    context.mqs['processing tasks'] = multiprocessing.Queue()
    context.mqs['verification obj desc files'] = multiprocessing.Queue()
    context.mqs['verification obj descs num'] = multiprocessing.Queue()


@core.components.after_callback
def __prepare_descriptions_file(context):
    context.mqs['verification obj desc files'].put(
        os.path.relpath(context.VO_FILE, context.conf['main working directory']))


@core.components.after_callback
def __submit_project_attrs(context):
    context.mqs['VTG common prj attrs'].put(context.common_prj_attrs)


def _extract_plugin_descs(logger, tmpl_id, tmpl_desc):
    logger.info('Extract descriptions for plugins of template "{0}"'.format(tmpl_id))

    if 'plugins' not in tmpl_desc:
        raise ValueError(
            'Template "{0}" has not mandatory attribute "plugins"'.format(tmpl_id))

    # Copy plugin descriptions since we will overwrite them while the same template can be used by different requirement
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


def _extract_requirement_desc(logger, raw_requirement_descs, requirement_id):
    logger.info('Extract description for requirement "{0}"'.format(requirement_id))

    categories = requirement_id.split(':')
    desc = raw_requirement_descs['requirements']
    tmpl_id = None
    while categories:
        c = categories.pop(0)
        if c in desc:
            desc = desc[c]
            tmpl_id = desc.get('template', tmpl_id)
        else:
            desc = None
            break
    if desc:
        requirement_desc = desc
    else:
        raise ValueError('Specified requirement "{0}" could not be found in requirements DB'.format(requirement_id))

    # Get rid of useless information.
    for attr in ('description',):
        if attr in requirement_desc:
            del (requirement_desc[attr])

    # Get requirement template which it is based on.
    if not tmpl_id:
        raise ValueError('Requirement "{0}" has not mandatory attribute "template"'.format(requirement_id))
    # This information won't be used any more.
    if 'template' in requirement_desc:
        del requirement_desc['template']
    logger.debug('Requirement specification "{0}" template is "{1}"'.format(requirement_id, tmpl_id))
    if 'templates' not in raw_requirement_descs or tmpl_id not in raw_requirement_descs['templates']:
        raise ValueError(
            'Template "{0}" of requirement specification "{1}" could not be found in requirements DB'.format(
                tmpl_id, requirement_id))
    tmpl_desc = raw_requirement_descs['templates'][tmpl_id]

    # Get options for plugins specified in template.
    plugin_descs = _extract_plugin_descs(logger, tmpl_id, tmpl_desc)

    # Get options for plugins specified in base template and merge them with the ones extracted above.
    if 'template' in tmpl_desc:
        if tmpl_desc['template'] not in raw_requirement_descs['templates']:
            raise ValueError('Template "{0}" of template "{1}" could not be found in requirements DB'.format(
                tmpl_desc['template'], tmpl_id))

        logger.debug('Template "{0}" template is "{1}"'.format(tmpl_id, tmpl_desc['template']))

        base_tmpl_plugin_descs = _extract_plugin_descs(logger, tmpl_desc['template'],
                                                       raw_requirement_descs['templates'][tmpl_desc['template']])

        for plugin_desc in plugin_descs:
            for base_tmpl_plugin_desc in base_tmpl_plugin_descs:
                if plugin_desc['name'] == base_tmpl_plugin_desc['name']:
                    if 'options' in base_tmpl_plugin_desc:
                        if 'options' in plugin_desc:
                            plugin_desc['options'] = core.utils.merge_confs(base_tmpl_plugin_desc['options'],
                                                                            plugin_desc['options'])
                        else:
                            plugin_desc['options'] = base_tmpl_plugin_desc['options']

    # Add plugin options specific for requirement specification.
    requirement_plugin_names = []
    # Names of all remained attributes are considered as plugin names, values - as corresponding plugin options.
    for attr in requirement_desc:
        plugin_name = attr
        requirement_plugin_names.append(plugin_name)
        is_plugin_specified = False

        for plugin_desc in plugin_descs:
            if plugin_name == plugin_desc['name']:
                is_plugin_specified = True
                if 'options' not in plugin_desc:
                    plugin_desc['options'] = {}
                plugin_desc['options'].update(requirement_desc[plugin_name])
                logger.debug(
                    'Plugin "{0}" options specific for requirement specification "{1}" are "{2}"'.format(
                        plugin_name, requirement_id, requirement_desc[plugin_name]))
                break

        if not is_plugin_specified:
            raise ValueError(
                'Requirement specification "{0}" plugin "{1}" is not specified in template "{2}"'.format(
                    requirement_id, plugin_name, tmpl_id))

    # We don't need to keep plugin options specific for requirement specification in such the form any more.
    for plugin_name in requirement_plugin_names:
        del (requirement_desc[plugin_name])

    requirement_desc['plugins'] = plugin_descs

    # Add requirement identifier to its description after all. Do this so late to avoid treating of "id" as
    # plugin name above.
    requirement_desc['id'] = requirement_id

    return requirement_desc


# This function is invoked to collect plugin callbacks.
def _extract_requirement_descs(conf, logger):
    logger.info('Extract requirement specificaction decriptions')

    if 'requirements DB' not in conf:
        logger.warning('Nothing will be verified since requirements DB is not specified')
        return []

    if 'requirements' not in conf:
        logger.warning('Nothing will be verified since requirements are not specified')
        return []

    if 'specifications set' not in conf:
        logger.warning('Nothing will be verified since specifications set is not specified')
        return []

    # Read requirement specification descriptions DB.
    with open(conf['requirements DB'], encoding='utf8') as fp:
        raw_requirement_descs = json.load(fp)

    if 'requirements' not in raw_requirement_descs:
        raise KeyError('Requirements DB has not mandatory attribute "requirements"')

    if 'all' in conf['requirements']:
        if not len(conf['requirements']) == 1:
            raise ValueError(
                'You can not specify "all" requirements together with some other requirements')

        # Add all requirements identifiers from DB.
        conf['requirements'] = sorted(raw_requirement_descs['requirements'].keys())

        # Remove all empty requirements since they are intended for development.
        requirements = []
        for requirement_id in conf['requirements']:
            if requirement_id.find('empty') == -1 and requirement_id.find('test') == -1:
                requirements.append(requirement_id)
        conf['requirements'] = requirements
        logger.debug('Following requirements will be checked "{0}"'.format(conf['requirements']))

    requirement_descs = []

    for requirement_id in conf['requirements']:
        requirement_descs.append(_extract_requirement_desc(logger, raw_requirement_descs, requirement_id))

    if conf['keep intermediate files']:
        if os.path.isfile('requirements descs.json'):
            raise FileExistsError('Requirements descriptions file "requirements descs.json" already exists')
        logger.debug('Create requirements descriptions file "requirements descs.json"')
        with open('requirements descs.json', 'w', encoding='utf8') as fp:
            json.dump(requirement_descs, fp, ensure_ascii=False, sort_keys=True, indent=4)

    return requirement_descs


def _classify_requirement_descriptions(logger, requirement_descriptions):
    # Determine requirement classes
    requirement_classes = {}
    for requirement_desc in requirement_descriptions:
        hashes = dict()
        for plugin in (p for p in requirement_desc['plugins'] if p['name'] in ['SA', 'EMG']):
            hashes[plugin['name']] = plugin['options']

        if len(hashes) > 0:
            opt_cache = hashlib.sha224(str(hashes).encode('UTF8')).hexdigest()
            if opt_cache in requirement_classes:
                requirement_classes[opt_cache].append(requirement_desc)
            else:
                requirement_classes[opt_cache] = [requirement_desc]
        else:
            requirement_classes[requirement_desc['id']] = [requirement_desc]
    logger.info("Generated {} requirement classes from given descriptions".format(len(requirement_classes)))
    return requirement_classes


_requirement_descs = None
_requirement_classes = None


@core.components.propogate_callbacks
def collect_plugin_callbacks(conf, logger):
    logger.info('Get VTG plugin callbacks')

    global _requirement_descs, _requirement_classes
    _requirement_descs = _extract_requirement_descs(conf, logger)
    _requirement_classes = _classify_requirement_descriptions(logger, _requirement_descs)
    plugins = []

    # Find appropriate classes for plugins if so.
    for requirement_desc in _requirement_descs:
        for plugin_desc in requirement_desc['plugins']:
            logger.info('Load plugin "{0}"'.format(plugin_desc['name']))
            try:
                plugin = getattr(importlib.import_module('.{0}'.format(plugin_desc['name'].lower()), 'core.vtg'),
                                 plugin_desc['name'])
                # Remember found class to create its instance during main operation.
                plugin_desc['plugin'] = plugin
                if plugin not in plugins:
                    plugins.append(plugin)
            except ImportError:
                raise NotImplementedError('Plugin {0} is not supported'.format(plugin_desc['name']))

    return core.components.get_component_callbacks(logger, plugins, conf)


def resolve_requirement_class(name):
    if len(_requirement_classes) > 0:
        rc = [identifier for identifier in _requirement_classes if name in
              [r['id'] for r in _requirement_classes[identifier]]][0]
    else:
        rc = None
    return rc


class VTG(core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(VTG, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                  separate_from_parent, include_child_resources)
        self.model_headers = {}
        self.requirement_descs = None

    def generate_verification_tasks(self):
        self.requirement_descs = _requirement_descs
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
        if not self.conf['keep intermediate files']:
            self.mqs['delete dir'] = multiprocessing.Queue()
        subcomponents = [('AAVTDG', self.__generate_all_abstract_verification_task_descs), VTGWL]
        self.launch_subcomponents(False, *subcomponents)

        self.clean_dir = True

        self.mqs['pending tasks'].put(None)
        self.mqs['pending tasks'].close()

    main = generate_verification_tasks

    def __generate_all_abstract_verification_task_descs(self):
        self.logger.info('Generate all abstract verification task decriptions')

        # Fetch object
        vo_file = self.mqs['verification obj desc files'].get()
        vo_file = os.path.join(self.conf['main working directory'], vo_file)
        self.mqs['verification obj desc files'].close()

        if os.path.isfile(vo_file):
            with open(vo_file, 'r', encoding='utf8') as fp:
                verification_obj_desc_files = \
                    [os.path.join(self.conf['main working directory'], vof.strip()) for vof in fp.readlines()]
        else:
            raise FileNotFoundError

        # Drop a line to a progress watcher
        total_vo_descriptions = len(verification_obj_desc_files)
        self.mqs['total tasks'].put([self.conf['sub-job identifier'],
                                     int(total_vo_descriptions * len(self.requirement_descs))])

        vo_descriptions = dict()
        initial = dict()

        # Fetch object
        for verification_obj_desc_file in verification_obj_desc_files:
            with open(os.path.join(self.conf['main working directory'], verification_obj_desc_file),
                      encoding='utf8') as fp:
                verification_obj_desc = json.load(fp)
            if not self.conf['keep intermediate files']:
                os.remove(os.path.join(self.conf['main working directory'], verification_obj_desc_file))
            if len(self.requirement_descs) == 0:
                self.logger.warning('Verification object {0} will not be verified since requirements'
                                    ' are not specified'.format(verification_obj_desc['id']))
            else:
                vo_descriptions[verification_obj_desc['id']] = verification_obj_desc
                initial[verification_obj_desc['id']] = list(_requirement_classes.keys())

        processing_status = dict()
        delete_ready = dict()
        balancer = Balancer(self.conf, self.logger, processing_status)

        def submit_task(vobj, rlcl, rlda, rescheduling=False):
            resource_limitations = balancer.resource_limitations(vobj['id'], rlcl, rlda['id'])
            self.mqs['prepare verification objects'].put((vobj, rlda, resource_limitations, rescheduling))

        max_tasks = int(self.conf['max solving tasks per sub-job'])
        active_tasks = 0
        while True:
            # Fetch pilot statuses
            pilot_statuses = []
            # This queue will not inform about the end of tasks generation
            core.utils.drain_queue(pilot_statuses, self.mqs['prepared verification tasks'])
            # Process them
            for status in pilot_statuses:
                vobject, requirement_name = status
                self.logger.info("Pilot verificatio task for {!r} and requirement name {!r} is prepared".
                                 format(vobject, requirement_name))
                requirement_class = resolve_requirement_class(requirement_name)
                if requirement_class:
                    if vobject in processing_status and requirement_class in processing_status[vobject] and \
                            requirement_name in processing_status[vobject][requirement_class]:
                        processing_status[vobject][requirement_class][requirement_name] = False
                else:
                    self.logger.warning("Do nothing with {} since no requirements to check".format(vobject))

            # Fetch solutions
            solutions = []
            # This queue will not inform about the end of tasks generation
            core.utils.drain_queue(solutions, self.mqs['processed tasks'])

            if not self.conf['keep intermediate files']:
                ready = []
                core.utils.drain_queue(ready, self.mqs['delete dir'])
                while len(ready) > 0:
                    vo, requirement = ready.pop()
                    if vo not in delete_ready:
                        delete_ready[vo] = {requirement}
                    else:
                        delete_ready[vo].add(requirement)

            # Process them
            for solution in solutions:
                vobject, requirement_name, status_info = solution
                self.logger.info("Verificatio task for {!r} and requirement {!r} is either finished or failed".
                                 format(vobject, requirement_name))
                requirement_class = resolve_requirement_class(requirement_name)
                if requirement_class:
                    final = balancer.add_solution(vobject, requirement_class, requirement_name, status_info)
                    if final:
                        self.mqs['finished and failed tasks'].put([self.conf['sub-job identifier'], 'finished'
                                                                  if status_info[0] == 'finished' else 'failed'])
                        processing_status[vobject][requirement_class][requirement_name] = True
                    active_tasks -= 1

            # Submit initial objects
            for vo in list(initial.keys()):
                while len(initial[vo]) > 0:
                    if active_tasks < max_tasks:
                        requirement_class = initial[vo].pop()
                        vobject = vo_descriptions[vo]
                        requirement_name = _requirement_classes[requirement_class][0]['id']
                        self.logger.info("Prepare initial verification tasks for {!r} and requirement {!r}".
                                         format(vo, requirement_name))
                        submit_task(vobject, requirement_class, _requirement_classes[requirement_class][0])

                        # Set status
                        if vo not in processing_status:
                            processing_status[vo] = {}
                        processing_status[vo][requirement_class] = {requirement_name: None}
                        active_tasks += 1
                    else:
                        break
                else:
                    self.logger.info("Trggered all initial tasks for verification object {!r}".format(vo))
                    del initial[vo]

            # Check statuses
            for vobject in list(processing_status.keys()):
                for requirement_class in list(processing_status[vobject].keys()):
                    # Check readiness for further tasks generation
                    pilot_task_status = processing_status[vobject][requirement_class][_requirement_classes[requirement_class][0]['id']]
                    if (pilot_task_status is False or pilot_task_status is True) and active_tasks < max_tasks:
                        for requirement in [requirement for requirement in _requirement_classes[requirement_class][1:] if
                                            requirement['id'] not in processing_status[vobject][requirement_class]]:
                            if active_tasks < max_tasks:
                                self.logger.info("Submit next verification task after having cached plugin results for "
                                                 "verification object {!r} and requirement {!r}".format(vobject, requirement['id']))
                                submit_task(vo_descriptions[vobject], requirement_class, requirement)
                                processing_status[vobject][requirement_class][requirement['id']] = None
                                active_tasks += 1
                            else:
                                break

                    # Check that we should reschedule tasks
                    for requirement in (r for r in _requirement_classes[requirement_class] if
                                 r['id'] in processing_status[vobject][requirement_class] and
                                 not processing_status[vobject][requirement_class][r['id']] and
                                 balancer.is_there(vobject, requirement_class, r['id'])):
                        if active_tasks < max_tasks:
                            attempt = balancer.do_rescheduling(vobject, requirement_class, requirement['id'])
                            if attempt:
                                self.logger.info("Submit task {}:{} to solve it again".format(vobject, requirement['id']))
                                submit_task(vo_descriptions[vobject], requirement_class, requirement, rescheduling=attempt)
                                active_tasks += 1
                            elif not balancer.need_rescheduling(vobject, requirement_class, requirement['id']):
                                self.logger.info("Mark task {}:{} as solved".format(vobject, requirement['id']))
                                self.mqs['finished and failed tasks'].put([self.conf['sub-job identifier'], 'finished'])
                                processing_status[vobject][requirement_class][requirement['id']] = True

                    # Number of solved tasks
                    solved = sum((1 if processing_status[vobject][requirement_class].get(r['id']) else 0
                                  for r in _requirement_classes[requirement_class]))
                    # Number of requirements which are ready to delete
                    deletable = len([r for r in processing_status[vobject][requirement_class]
                                     if vobject in delete_ready and r in delete_ready[vobject]])
                    # Total tasks for requirements
                    total = len(_requirement_classes[requirement_class])

                    if solved == total and (self.conf['keep intermediate files'] or
                                            (vobject in delete_ready and solved == deletable)):
                        self.logger.debug("Solved {} tasks for verification object {!r}".format(solved, vobject))
                        if not self.conf['keep intermediate files']:
                            for requirement in processing_status[vobject][requirement_class]:
                                deldir = os.path.join(vobject, requirement)
                                core.utils.reliable_rmtree(self.logger, deldir)
                        del processing_status[vobject][requirement_class]

                if len(processing_status[vobject]) == 0 and vobject not in initial:
                    self.logger.info("All tasks for verification object {!r} are either solved or failed".
                                     format(vobject))
                    # Verification object is lastly processed
                    del processing_status[vobject]
                    del vo_descriptions[vobject]
                    if vobject in delete_ready:
                        del delete_ready[vobject]

            if active_tasks == 0 and len(vo_descriptions) == 0 and len(initial) == 0:
                self.mqs['prepare verification objects'].put(None)
                self.mqs['prepared verification tasks'].close()
                if not self.conf['keep intermediate files']:
                    self.mqs['delete dir'].close()
                break
            else:
                self.logger.debug("There are {} initial tasks to be generated, {} active tasks, {} verification object "
                                  "descriptions".format(len(initial), active_tasks, len(vo_descriptions)))

            time.sleep(3)

        self.logger.info("Stop generating verification tasks")

    def __get_common_prj_attrs(self):
        self.logger.info('Get common project atributes')
        common_prj_attrs = self.mqs['VTG common prj attrs'].get()
        self.mqs['VTG common prj attrs'].close()
        return common_prj_attrs


class VTGWL(core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(VTGWL, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                    separate_from_parent, include_child_resources)

    def task_generating_loop(self):
        self.logger.info("Start VTGL worker")
        number = core.utils.get_parallel_threads_num(self.logger, self.conf, 'Tasks generation')
        core.components.launch_queue_workers(self.logger, self.mqs['prepare verification objects'],
                                             self.vtgw_constructor, number, True)
        self.logger.info("Terminate VTGL worker")

    def vtgw_constructor(self, element):
        attrs = [
            {
                "name": "Requirement",
                "value": element[1]['id']
            }
        ]
        if element[3]:
            identifier = "{}/{}/{}/VTGW".format(element[0]['id'], element[1]['id'], element[3])
            workdir = os.path.join(element[0]['id'], element[1]['id'], str(element[3]))
            attrs.append({
                "name": "Rescheduling attempt",
                "value": str(element[3]),
                "compare": False,
                "associate": False
            })
        else:
            identifier = "{}/{}/VTGW".format(element[0]['id'], element[1]['id'])
            workdir = os.path.join(element[0]['id'], element[1]['id'])
        return VTGW(self.conf, self.logger, self.parent_id, self.callbacks, self.mqs,
                    self.vals, identifier, workdir,
                    attrs=attrs, separate_from_parent=True, verification_object=element[0], requirement=element[1],
                    resource_limits=element[2], rerun=element[3])

    main = task_generating_loop


class VTGW(core.components.Component):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False, verification_object=None, requirement=None,
                 resource_limits=None, rerun=False):
        super(VTGW, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                   separate_from_parent, include_child_resources)
        self.verification_object = verification_object
        self.requirement = requirement
        self.abstract_task_desc_file = None
        self.override_limits = resource_limits
        self.rerun = rerun
        self.session = core.session.Session(self.logger, self.conf['Klever Bridge'], self.conf['identifier'])
        self.clade = clade_api
        self.clade.setup(self.conf['build base'])

    def tasks_generator_worker(self):
        files_list_file = 'files list.txt'
        with open(files_list_file, 'w', encoding='utf8') as fp:
            fp.writelines('\n'.join(sorted(f for grp in self.verification_object['grps'] for f in grp['files'])))
        core.utils.report(self.logger,
                          'attrs',
                          {
                              'id': self.id,
                              'attrs': [
                                  {
                                      "name": "Verification object",
                                      "value": self.verification_object['id'],
                                      "data": files_list_file,
                                      "compare": True,
                                      "associate": True
                                  }
                              ]
                          },
                          self.mqs['report files'],
                          self.vals['report id'],
                          self.conf['main working directory'],
                          data_files=[files_list_file])

        try:
            self.generate_abstact_verification_task_desc(self.verification_object, self.requirement)
            if not self.vals['task solving flag'].value:
                with self.vals['task solving flag'].get_lock():
                    self.vals['task solving flag'].value = 1
        except Exception:
            self.plugin_fail_processing()
            raise
        finally:
            self.session.sign_out()

    main = tasks_generator_worker

    def generate_abstact_verification_task_desc(self, verification_obj_desc, requirement_desc):
        """Has a callback!"""
        self.logger.info("Start generating tasks for verification object {!r} and requirement {!r}".
                         format(verification_obj_desc['id'], requirement_desc['id']))
        verification_object = verification_obj_desc['id']
        self.requirement = requirement_desc['id']

        # Prepare pilot workdirs if it will be possible to reuse data
        requirement_class = resolve_requirement_class(requirement_desc['id'])
        pilot_requirement = _requirement_classes[requirement_class][0]['id']
        pilot_plugins_work_dir = os.path.join(os.path.pardir, pilot_requirement)

        # Initial abstract verification task looks like corresponding verification object.
        initial_abstract_task_desc = copy.deepcopy(verification_obj_desc)
        initial_abstract_task_desc['id'] = '{0}/{1}'.format(verification_object, self.requirement)
        initial_abstract_task_desc['attrs'] = ()
        for grp in initial_abstract_task_desc['grps']:
            grp['Extra CCs'] = []

            for cc in grp['CCs']:
                in_file = self.clade.get_cc(cc)['in'][0]
                grp['Extra CCs'].append({
                    'CC': cc,
                    'in file': in_file
                })

            del (grp['CCs'])
        initial_abstract_task_desc_file = 'initial abstract task.json'
        self.logger.debug(
            'Put initial abstract verification task description to file "{0}"'.format(
                initial_abstract_task_desc_file))
        with open(initial_abstract_task_desc_file, 'w', encoding='utf8') as fp:
            json.dump(initial_abstract_task_desc, fp, ensure_ascii=False, sort_keys=True, indent=4)

        # Invoke all plugins one by one.
        cur_abstract_task_desc_file = initial_abstract_task_desc_file
        out_abstract_task_desc_file = None
        if self.rerun:
            # Get only the last, and note that the last one prepares tasks and otherwise rerun should not be set
            plugins = [requirement_desc['plugins'][-1]]
        else:
            plugins = requirement_desc['plugins']

        for plugin_desc in plugins:
            # Here plugin will put modified abstract verification task description.
            plugin_work_dir = plugin_desc['name'].lower()
            out_abstract_task_desc_file = '{0} abstract task.json'.format(plugin_desc['name'].lower())
            if self.rerun:
                self.logger.info("Instead of running the {!r} plugin for the {!r} requirement in the same dir obtain "
                                 "results for the original run".format(plugin_desc['name'], self.requirement))
                cur_abstract_task_desc_file = os.path.join(os.pardir, out_abstract_task_desc_file)
                os.symlink(os.path.relpath(cur_abstract_task_desc_file, os.path.curdir),
                           out_abstract_task_desc_file)

            if requirement_desc['id'] not in [c[0]['id'] for c in _requirement_classes.values()] and \
                    plugin_desc['name'] in ['SA', 'EMG']:
                # Expect that there is a work directory which has all prepared
                # Make symlinks to the pilot requirement work dir
                self.logger.info("Instead of running the {!r} plugin for the {!r} requirement lets use already obtained"
                                 " results for the {!r} requirement".format(plugin_desc['name'], self.requirement,
                                                                            pilot_requirement))
                pilot_plugin_work_dir = os.path.join(pilot_plugins_work_dir, plugin_desc['name'].lower())
                pilot_abstract_task_desc_file = os.path.join(
                    pilot_plugins_work_dir, '{0} abstract task.json'.format(plugin_desc['name'].lower()))
                os.symlink(os.path.relpath(pilot_abstract_task_desc_file, os.path.curdir),
                           out_abstract_task_desc_file)
                os.symlink(os.path.relpath(pilot_plugin_work_dir, os.path.curdir), plugin_work_dir)
            else:
                self.logger.info('Launch plugin {0}'.format(plugin_desc['name']))

                # Get plugin configuration on the basis of common configuration, plugin options specific for requirement
                # specification and information on requirement itself. In addition put either initial or
                # current description of abstract verification task into plugin configuration.
                plugin_conf = copy.deepcopy(self.conf)
                if 'options' in plugin_desc:
                    plugin_conf.update(plugin_desc['options'])
                if 'bug kinds' in requirement_desc:
                    plugin_conf.update({'bug kinds': requirement_desc['bug kinds']})
                plugin_conf['in abstract task desc file'] = os.path.relpath(cur_abstract_task_desc_file,
                                                                            self.conf[
                                                                                'main working directory'])
                plugin_conf['out abstract task desc file'] = os.path.relpath(out_abstract_task_desc_file,
                                                                             self.conf[
                                                                                 'main working directory'])
                plugin_conf['solution class'] = self.requirement
                plugin_conf['override resource limits'] = self.override_limits

                plugin_conf_file = '{0} conf.json'.format(plugin_desc['name'].lower())
                self.logger.debug(
                    'Put configuration of plugin "{0}" to file "{1}"'.format(plugin_desc['name'],
                                                                             plugin_conf_file))
                with open(plugin_conf_file, 'w', encoding='utf8') as fp:
                    json.dump(plugin_conf, fp, ensure_ascii=False, sort_keys=True, indent=4)

                try:
                    p = plugin_desc['plugin'](plugin_conf, self.logger, self.id, self.callbacks, self.mqs,
                                              self.vals, plugin_desc['name'],
                                              plugin_work_dir, separate_from_parent=True,
                                              include_child_resources=True)
                    p.start()
                    p.join()
                except core.components.ComponentError:
                    self.plugin_fail_processing()
                    break

                if self.requirement in [c[0]['id'] for c in _requirement_classes.values()] and \
                        plugin_desc['name'] == 'EMG':
                    self.logger.debug("Signal to VTG that the cache preapred for the requirement {!r} is ready for the "
                                      "further use".format(pilot_requirement))
                    self.mqs['prepared verification tasks'].put((verification_object, self.requirement))

            cur_abstract_task_desc_file = out_abstract_task_desc_file
        else:
            final_abstract_task_desc_file = 'final abstract task.json'
            if not self.rerun:
                self.logger.debug(
                    'Put final abstract verification task description to file "{0}"'.format(
                        final_abstract_task_desc_file))
                # Final abstract verification task description equals to abstract verification task description received
                # from last plugin.
                os.symlink(os.path.relpath(out_abstract_task_desc_file, os.path.curdir),
                           final_abstract_task_desc_file)

            # VTG will consume this abstract verification task description file.
            self.abstract_task_desc_file = out_abstract_task_desc_file

            if os.path.isfile(os.path.join(plugin_work_dir, 'task.json')) and \
               os.path.isfile(os.path.join(plugin_work_dir, 'task files.zip')):
                task_id = self.session.schedule_task(os.path.join(plugin_work_dir, 'task.json'),
                                                     os.path.join(plugin_work_dir, 'task files.zip'))
                with open(self.abstract_task_desc_file, 'r', encoding='utf8') as fp:
                    final_task_data = json.load(fp)

                # Plan for checking status
                self.mqs['pending tasks'].put([
                    [str(task_id), final_task_data["result processing"], self.verification_object,
                     self.requirement, final_task_data['verifier']],
                    self.rerun
                ])
                self.logger.info("Submitted successfully verification task {} for solution".
                                 format(os.path.join(plugin_work_dir, 'task.json')))
            else:
                self.logger.warning("There is no verification task generated by the last plugin, expect {}".
                                    format(os.path.join(plugin_work_dir, 'task.json')))
                self.mqs['processed tasks'].put((verification_object, self.requirement, [None, None, None]))

    def plugin_fail_processing(self):
        """The function has a callback in sub-job processing!"""
        self.logger.debug("VTGW that processed {!r}, {!r} failed".
                          format(self.verification_object['id'], self.requirement))
        self.mqs['processed tasks'].put((self.verification_object['id'], self.requirement, [None, None, None]))

    def join(self, timeout=None, stopped=False):
        try:
            ret = super(VTGW, self).join(timeout, stopped)
        finally:
            if not self.conf['keep intermediate files'] and not self.is_alive():
                self.logger.debug("Indicate that the working directory can be deleted for: {!r}, {!r}".
                                  format(self.verification_object['id'], self.requirement['id']))
                self.mqs['delete dir'].put([self.verification_object['id'], self.requirement['id']])
        return ret
