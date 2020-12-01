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

from xml.etree import ElementTree


def adjust_options(file, conf):
    """
    Get a name of the verifier and the file with options. For each verifier there might be a function for tuning options
    and replacing file.

    :param file: XML file for BenchExec.
    :param conf: Dictionary with the configuration of the client.
    :return: None
    """
    if conf['verifier']['name'] == 'CPAchecker':
        cpa_adjustment(file, conf)


def cpa_adjustment(file, conf):
    """
    This function adds fixes to configuration.
        1. Change heap memory size to make it matching real restrictions.

    :param file: XML file for BenchExec.
    :param conf: Dictionary with the configuration of the client.
    :return:
    """
    tree = ElementTree.parse(file)
    root = tree.getroot()
    rewrite = False
    for rundefinition in root.findall('rundefinition'):
        for option in rundefinition.findall('option'):
            if option.attrib.get('name') == '-heap':
                # First, get coefficient
                restriction = int(conf['resource limits']['memory size'])
                # Expect value in MB
                heap = int(option.text[:-1]) * 1000000
                if heap >= int(restriction * 0.8):
                    # Then, recalculate value
                    new_heap = str(int(restriction * 0.0000008)) + 'm'
                    option.text = new_heap
                    rewrite = True

    if rewrite:
        tree.write(file, encoding='utf-8')
