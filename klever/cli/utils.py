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

import getpass
import logging
import os
import subprocess
import sys

PROMPT = 'Password: '


def execute_cmd(logger, *args, **kwargs):
    logger.info('Execute command "{0}"'.format(' '.join(args)))

    get_output = kwargs.pop('get_output') if 'get_output' in kwargs else False

    if get_output:
        return subprocess.check_output(args, **kwargs).decode('utf-8').rstrip().split('\n')
    else:
        subprocess.check_call(args, **kwargs)


def get_logger(name):
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s (%(filename)s:%(lineno)03d) %(levelname)s> %(message)s',
                                  "%Y-%m-%d %H:%M:%S")
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    return logger


def get_password(password):
    if password is not None and len(password) > 0:
        return password
    if sys.stdin.isatty():
        return getpass.getpass(PROMPT)
    else:
        print(PROMPT, end='', flush=True)
        return sys.stdin.readline().rstrip()


def make_relative_path(dirs, file_or_dir, absolutize=False):
    # Normalize paths first of all.
    dirs = [os.path.normpath(d) for d in dirs]
    file_or_dir = os.path.normpath(file_or_dir)

    # Check all dirs are absolute or relative.
    is_dirs_abs = False
    if all(os.path.isabs(d) for d in dirs):
        is_dirs_abs = True
    elif all(not os.path.isabs(d) for d in dirs):
        pass
    else:
        raise ValueError('Can not mix absolute and relative dirs')

    if os.path.isabs(file_or_dir):
        # Making absolute file_or_dir relative to relative dirs has no sense.
        if not is_dirs_abs:
            return file_or_dir
    else:
        # One needs to absolutize file_or_dir since it can be relative to Clade storage.
        if absolutize:
            if not is_dirs_abs:
                raise ValueError('Do not absolutize file_or_dir for relative dirs')

            file_or_dir = os.path.join(os.path.sep, file_or_dir)
        # file_or_dir is already relative.
        elif is_dirs_abs:
            return file_or_dir

    # Find and return if so path relative to the longest directory.
    for d in sorted(dirs, key=lambda t: len(t), reverse=True):
        # TODO: commonpath was supported just in Python 3.5.
        if os.path.commonpath([file_or_dir, d]) == d:
            return os.path.relpath(file_or_dir, d)

    return file_or_dir
