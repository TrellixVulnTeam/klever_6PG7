# Copyright (c) 2020 ISP RAS (http://www.ispras.ru)
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

import os


PYTHON = '/usr/local/python3-klever/bin/python3'
KLEVER_DEPLOY_LOCAL = os.path.join(os.path.dirname(PYTHON), 'klever-deploy-local')

OS_USER = 'debian'
OS_HOME = f'/home/{OS_USER}'
OS_AUTH_URL = 'https://sky.ispras.ru:13000'  # OpenStack identity service endpoint for authorization
OS_TENANT_NAME = 'computations'
OS_DOMAIN_NAME = 'ispras'

SRC_DIR = os.path.join(OS_HOME, 'klever')
DEPLOYMENT_DIR = os.path.join(OS_HOME, 'klever-inst')
STORAGE = os.path.join(OS_HOME, 'klever-storage')
PROD_MEDIA_DIR = os.path.join(DEPLOYMENT_DIR, 'klever-media')
DEV_MEDIA_DIR = os.path.join(SRC_DIR, 'bridge', 'media')
VOLUME_DIR = os.path.join(OS_HOME, 'volume')
VOLUME_MEDIA_DIR = os.path.join(VOLUME_DIR, 'media')
VOLUME_PGSQL_DIR = os.path.join(VOLUME_DIR, 'postgresql')
