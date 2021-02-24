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
from clade import Clade

import klever.core.utils
import klever.core.vtg.plugins
import klever.core.vtg.utils


class RSG(klever.core.vtg.plugins.Plugin):

    def __init__(self, conf, logger, parent_id, callbacks, mqs, vals, id=None, work_dir=None, attrs=None,
                 separate_from_parent=False, include_child_resources=False):
        super(RSG, self).__init__(conf, logger, parent_id, callbacks, mqs, vals, id, work_dir, attrs,
                                  separate_from_parent, include_child_resources)

    def generate_requirement(self):
        generated_models = {}

        if 'files' in self.abstract_task_desc:
            self.logger.info('Get generated aspects and models specified in abstract task description')

            for file in self.abstract_task_desc['files']:
                file = os.path.relpath(os.path.join(self.conf['main working directory'], file))
                ext = os.path.splitext(file)[1]
                if ext == '.c':
                    generated_models[file] = {}
                    self.logger.debug('Get generated model with C file "{0}'.format(file))
                elif ext == '.aspect':
                    self.logger.debug('Get generated aspect "{0}'.format(file))
                else:
                    raise ValueError('Files with extension "{0}" are not supported'.format(ext))

        self.add_models(generated_models)

        if 'files' in self.abstract_task_desc:
            self.abstract_task_desc.pop('files')

    main = generate_requirement

    def add_models(self, generated_models):
        self.logger.info('Add models to abstract verification task description')

        models = []
        if 'environment model' in self.abstract_task_desc:
            models.append({
                'model': os.path.relpath(os.path.join(self.conf['main working directory'],
                                                      self.abstract_task_desc['environment model']),
                                         os.path.curdir),
                'options': {},
                'generated': True
            })

        if 'extra C files' in self.abstract_task_desc:
            self.abstract_task_desc['extra C files'] = []
            for c_file in (extra_c_file["C file"] for extra_c_file in self.abstract_task_desc['extra C files']
                           if "C file" in extra_c_file):
                models.append(os.path.relpath(os.path.join(self.conf['main working directory'], c_file),
                                              os.path.curdir))

        def get_model_c_file(model):
            # Model may be a C file or a dictionary with model file and option attributes.
            if isinstance(model, dict):
                return model['model']
            else:
                return model

        # Get common and requirement specific models.
        if 'common models' in self.conf and 'models' in self.conf:
            for common_model_c_file in self.conf['common models']:
                for model in self.conf['models']:
                    if common_model_c_file == get_model_c_file(model):
                        raise KeyError('C file "{0}" is specified in both common and requirement specific models'
                                       .format(common_model_c_file))

        if 'models' in self.conf:
            # Find out actual C files.
            for model in self.conf['models']:
                model_c_file = get_model_c_file(model)

                # Handle generated models which C files start with "$".
                if model_c_file.startswith('$'):
                    is_generated_model_c_file_found = False
                    for generated_model_c_file in generated_models:
                        if generated_model_c_file.endswith(model_c_file[1:]):
                            if isinstance(model, dict):
                                # Specify model options for generated models that can not have model options themselves.
                                models.append({
                                    'model': generated_model_c_file,
                                    'options': model['options'],
                                    'generated': True
                                })
                            else:
                                models.append({
                                    'model': generated_model_c_file,
                                    'options': {},
                                    'generated': True
                                })
                            is_generated_model_c_file_found = True

                    if not is_generated_model_c_file_found:
                        raise KeyError('Model C file "{0}" was not generated'.format(model_c_file[1:]))
                # Handle non-generated models.
                else:
                    model_c_file_realpath = klever.core.vtg.utils.find_file_or_dir(
                        self.logger, self.conf['main working directory'], model_c_file)
                    self.logger.debug('Get model with C file "{0}"'.format(model_c_file_realpath))

                    if isinstance(model, dict):
                        models.append({
                            'model': model_c_file_realpath,
                            'options': model['options']
                        })
                    else:
                        models.append(model_c_file_realpath)

        # Like for models above except for common models are always C files without any model settings.
        if 'common models' in self.conf:
            for common_model_c_file in self.conf['common models']:
                common_model_c_file_realpath = klever.core.vtg.utils.find_file_or_dir(
                    self.logger, self.conf['main working directory'], common_model_c_file)
                self.logger.debug('Get common model with C file "{0}"'.format(common_model_c_file_realpath))
                models.append(common_model_c_file_realpath)

        self.logger.debug('Resulting models are: {0}'.format(models))

        if not models:
            self.logger.warning('No models are specified')
            return

        # CC extra full description files will be put to this directory as well as corresponding intermediate and final
        # output files.
        os.makedirs('models'.encode('utf-8'))

        self.logger.info('Add aspects to abstract verification task description')
        aspects = []
        for model in models:
            aspect = '{}.aspect'.format(os.path.splitext(get_model_c_file(model))[0])

            if not os.path.isfile(aspect):
                continue

            self.logger.debug('Get aspect "{0}"'.format(aspect))

            aspects.append(aspect)

        # Sort aspects to apply them in the deterministic order.
        aspects.sort()

        for grp in self.abstract_task_desc['grps']:
            self.logger.info('Add aspects to C files of group "{0}"'.format(grp['id']))
            for extra_cc in grp['Extra CCs']:
                if 'plugin aspects' not in extra_cc:
                    extra_cc['plugin aspects'] = []
                extra_cc['plugin aspects'].append({
                    'plugin': self.name,
                    'aspects': [os.path.relpath(aspect, self.conf['main working directory']) for aspect in aspects]
                })

        # Generate CC full description file per each model and add it to abstract task description.
        # First of all obtain CC options to be used to compile models.
        clade = Clade(self.conf['build base'])
        if not clade.work_dir_ok():
            raise RuntimeError('Build base is not OK')
        meta = clade.get_meta()

        if not meta['conf'].get('Compiler.preprocess_cmds', False):
            # Model compiler input file represents input file which compiler options and CWD should be used for
            # compiling models. This input file is relative to one of source paths.
            compiler_cmds = None
            for path in self.conf['working source trees']:
                try:
                    compiler_cmds = list(clade.get_compilation_cmds_by_file(
                        os.path.normpath(os.path.join(path, self.conf['model compiler input file']))))
                except KeyError:
                    pass

            if not compiler_cmds:
                raise RuntimeError("There is no compiler commands for {!r}"
                                   .format(self.conf['model compiler input file']))
            elif len(compiler_cmds) > 1:
                self.logger.warning("There are more than one compiler command for {!r}".
                                    format(self.conf['model compiler input file']))

            model_compiler_opts = clade.get_cmd_opts(compiler_cmds[0]['id'])
            model_compiler_cwd = compiler_cmds[0]['cwd']
        else:
            # No specific compiler options are necessary for models.
            model_compiler_opts = []
            if len(self.conf['working source trees']) != 1:
                raise NotImplementedError('There are several working source trees!')
            model_compiler_cwd = self.conf['working source trees'][0]

        model_grp = {'id': 'models', 'Extra CCs': []}
        for model in sorted(models, key=get_model_c_file):
            model_c_file = get_model_c_file(model)
            file, ext = os.path.splitext(os.path.join('models', os.path.basename(model_c_file)))
            base_name = klever.core.utils.unique_file_name(file, '{0}.json'.format(ext))
            full_desc_file = '{0}{1}.json'.format(base_name, ext)
            out_file = '{0}.c'.format(base_name)

            # Always specify either specific model sets model or common one.
            opts = ['-DLDV_SETS_MODEL_' + (model['options']['sets model']
                                           if isinstance(model, dict) and 'sets model' in model['options']
                                           else self.conf['common sets model']).upper()]
            if 'specifications set' in self.conf:
                opts += ['-DLDV_SPECS_SET_{0}'.format(self.conf['specifications set'].replace('.', '_'))]

            self.logger.debug('Dump CC full description to file "{0}"'.format(full_desc_file))
            with open(full_desc_file, 'w', encoding='utf-8') as fp:
                klever.core.utils.json_dump({
                    'cwd': model_compiler_cwd,
                    'in': [os.path.realpath(model_c_file)],
                    'out': [os.path.realpath(out_file)],
                    'opts': model_compiler_opts + opts
                }, fp, self.conf['keep intermediate files'])

            extra_cc = {'CC': os.path.relpath(full_desc_file, self.conf['main working directory'])}
            if 'generated' in model:
                extra_cc['generated'] = True
            model_grp['Extra CCs'].append(extra_cc)

        self.abstract_task_desc['grps'].append(model_grp)
        for dep in self.abstract_task_desc['deps'].values():
            dep.append(model_grp['id'])
