import os
import json
import shutil

from core.lkvog.module_extractors import util


class LinuxKernel:
    def __init__(self, logger, clade, conf):
        self.logger = logger
        self.clade = clade
        self.modules = conf.get('modules', True)
        self.kernel = conf.get('kernel')

    def divide(self):
        modules = {}

        cmd_graph = self.clade.get_command_graph()
        build_graph = cmd_graph.load()

        for id, desc in build_graph.items():
            if desc['type'] == 'LD':
                full_desc = util.get_full_desc(self.clade, id, desc['type'])
                if self.modules and full_desc['out'].endswith('.ko'):
                    modules.update(util.create_module_by_ld(self.clade, id, build_graph))
                if self.kernel and not full_desc['out'].endswith('.ko') and not desc['used_by']:
                    modules.update(util.create_module_by_ld(self.clade, id, build_graph))

        return modules
