#!/usr/bin/env python3
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

import os
import json

from utils.utils import get_args_parser, Session

parser = get_args_parser('Start solution of verification job.')
parser.add_argument('identifier', help='Verification job identifier.')
parser.add_argument('--copy', action='store_true',
                    help='Set it if you would like to copy verification job before starting solution.')
parser.add_argument('--replacement',
                    help='JSON file name or string with data what files should be replaced before starting solution.')
parser.add_argument('--rundata', type=open,
                    help='JSON file name. Set it if you would like to start solution with specific settings.')
args = parser.parse_args()

with Session(args) as session:
    job_id = args.identifier
    if args.copy:
        job_id = session.copy_job(args.identifier)
    elif args.replacement:
        session.copy_job_version(args.identifier)

    # Replace files before start
    if args.replacement:
        if os.path.exists(args.replacement):
            with open(args.replacement, mode='r', encoding='utf8') as fp:
                new_files = json.load(fp)
        else:
            new_files = json.loads(args.replacement)
        session.replace_files(job_id, new_files)

    session.start_job_decision(job_id, args.rundata)

print('Solution of verification job "{0}" was successfully started'.format(args.identifier))