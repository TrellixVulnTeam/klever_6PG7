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

import os
import shutil
import ujson
import zipfile


from core.vog.common import Aggregation
from core.vog.aggregation.abstract import Abstract
import core.utils


class Coverage(Abstract):
    """
    This strategy gets information about coverage of fragments and searches for suitable fragments to add to cover
    functions exported by target ones.
    """

    def __init__(self, logger, conf, divider):
        super(Coverage, self).__init__(logger, conf, divider)
        self.fragments_map = self.conf['Aggregation strategy'].get('coverage archive')
        self._black_list = set(self.conf['Aggregation strategy'].get('ignore fragments', {}))
        self._white_list = set(self.conf['Aggregation strategy'].get('prefer fragments', {}))

        # Get archive
        archive = core.utils.find_file_or_dir(self.logger, self.conf['main working directory'],
                                              self.conf['Aggregation strategy']['coverage archive'])

        # Extract/fetch file
        with zipfile.ZipFile(archive) as z:
            with z.open('coverage.json') as zf:
                coverage = ujson.load(zf)

        # Extract information on functions
        self._func_coverage = coverage.get('functions statistics')
        if not self._func_coverage or not self._func_coverage.get('statistics'):
            raise ValueError("There is no statictics about functions in the given coverage archive")
        self._func_coverage = {p.replace('source files/', ''): v
                               for p, v in self._func_coverage.get('statistics').items()}
        self._func_coverage.pop('overall')

    def _aggregate(self):
        """
        Just return target fragments as aggregations consisting of a single fragment.

        :return: Generator that retursn Aggregation objects.
        """
        # Collect dependencies
        c_to_deps, f_to_deps, f_to_files, c_to_frag = self.divider.establish_dependencies()
        cg = self.clade.CallGraph().graph

        # Get target fragments
        for fragment in self.divider.target_fragments:
            # Search for export functions
            ranking = dict()
            function_map = dict()
            for path in fragment.export_functions:
                for func in fragment.export_functions[path]:
                    # Find fragments that call this function
                    relevant = self._find_fragments(fragment, path, func, cg, c_to_frag)
                    for rel in relevant:
                        ranking.setdefault(rel.name, 0)
                        ranking[rel.name] += 1
                        function_map.setdefault(func, set())
                        function_map[func].update(relevant)

            # Use a greedy algorythm. Go from functions that most rarely used and add fragments that most oftenly used
            # Turn into account white and black lists
            added = set()
            for func in (f for f in sorted(function_map.keys(), key=lambda x: len(function_map[x]))
                         if len(function_map[f])):
                if function_map[func].intersection(added):
                    # Already added
                    continue
                else:
                    possible = {f.name for f in function_map[func]}.intersection(self._white_list)
                    if not possible:
                        # Get rest
                        possible = {f.name for f in function_map[func]}.difference(self._black_list)
                    if possible:
                        added.add(sorted((f for f in function_map[func] if f.name in possible),
                                         key=lambda x: ranking[x.name], reverse=True)[0])

            # Now generate pairs
            aggs = []
            for frag in added:
                new = Aggregation(fragment)
                new.name = "{}:{}".format(fragment.name, frag.name)
                new.fragments.add(frag)
                aggs.append(new)
            new = Aggregation(fragment)
            new.name = fragment.name
            aggs.append(new)

            for agg in aggs:
                yield agg

        # Free data
        self._func_coverage = None

    def _find_fragments(self, fragment, path, func, cg, c_to_frag):
        """
        Find fragments that call given function in its covered functions.

        :param fragment: Fragment object.
        :param path: Definition function scope.
        :param func: Target function name.
        :param cg: Callgraph dict.
        :param c_to_frag: Dict with map of c files to fragment with this file.
        :return: A set of fragments.
        """
        result = set()
        # Get functions from the callgraph
        desc = cg.get(path, dict()).get(func)
        if desc:
            for scope, called_funcs in ((s, d) for s, d in desc.get('called_in', dict()).items()
                                        if s != path and s in self._func_coverage):
                if any(True for f in called_funcs if f in self._func_coverage[scope]):
                    # Found function call in covered functions retrieve Fragment and add to result
                    new = c_to_frag[scope]
                    if new in fragment.predecessors:
                        result.add(new)

        return result
