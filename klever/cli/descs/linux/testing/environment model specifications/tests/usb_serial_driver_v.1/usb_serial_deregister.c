/*
 * Copyright (c) 2018 ISP RAS (http://www.ispras.ru)
 * Ivannikov Institute for System Programming of the Russian Academy of Sciences
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <linux/module.h>
#include <linux/tty.h>
#include <linux/usb.h>
#include <linux/usb/serial.h>
#include <ldv/linux/emg/test_model.h>
#include <ldv/verifier/nondet.h>

const struct usb_device_id *id_table;

int ldv_probe(struct usb_serial *serial, const struct usb_device_id *id)
{
	ldv_invoke_callback();
	return 0;
}

void ldv_release(struct usb_serial *serial)
{
	ldv_invoke_callback();
}

static struct usb_serial_driver ldv_driver = {
	.probe = ldv_probe,
	.release = ldv_release,
};

static int __init ldv_init(void)
{
	int ret = ldv_undef_int();
	int flip_a_coin = ldv_undef_int();
	if (flip_a_coin) {
		ldv_register();
		ret = usb_serial_register(& ldv_driver);
		if (!ret)
			usb_serial_deregister(& ldv_driver);
		ldv_deregister();
	}
	return ret;
}

static void __exit ldv_exit(void)
{
	/* pass */
}

module_init(ldv_init);
module_exit(ldv_exit)

MODULE_LICENSE("GPL");
