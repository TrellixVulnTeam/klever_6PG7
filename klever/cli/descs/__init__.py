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

common_target_program_descs = {
    'Linux': {
        'source code': 'linux-stable',
        'git repository version': 'v3.14.79',
        'configuration': 'allmodconfig',
        'architecture': 'x86_64',
        'external modules header files search directory': os.path.join(os.path.dirname(__file__), 'include'),
        'loadable kernel modules': ['all'],
        'generate makefiles': True,
        'extra headers': [
            'linux/user_namespace.h',
            'linux/tty.h',
            'linux/tty_driver.h',
            'linux/usb.h',
            'linux/usb/serial.h',
            'linux/platform_device.h',
            'linux/netdevice.h',
            'linux/net.h',
            'linux/timer.h',
            'linux/interrupt.h',
            'linux/seq_file.h',
            'linux/i2c.h',
            'linux/mod_devicetable.h',
            'linux/device.h',
            'linux/pm.h',
            'linux/pm_runtime.h',
            'linux/fs.h',
            'linux/rtnetlink.h',
            'net/mac80211.h',
            'linux/iio/iio.h',
            'linux/iio/triggered_buffer.h',
            'linux/cdev.h',
            'linux/miscdevice.h',
            'linux/pci.h',
            'linux/rtc.h',
            'scsi/scsi_host.h',
            'linux/pagemap.h',
            'linux/poll.h',
            'linux/blkdev.h',
            'target/target_core_base.h',
            'target/target_core_backend.h',
            'linux/spi/spi.h',
            'linux/fb.h',
            'linux/firmware.h',
            'linux/dcache.h',
            "linux/statfs.h",
            "linux/mount.h",
            "linux/mtd/mtd.h",
            'media/v4l2-common.h',
            'media/v4l2-device.h'
        ]
    },
    "BusyBox": {
        'source code': 'busybox',
        'git repository version': '1_30_1',
        'configuration': 'defconfig',
        'architecture': 'x86_64'
    }
}

gcc46_clade_cif_opts = {"extra Clade options": {
    "Info.extra_CIF_opts": [
        "-D__GNUC__=4",
        "-D__GNUC_MINOR__=6"
    ]
}}
