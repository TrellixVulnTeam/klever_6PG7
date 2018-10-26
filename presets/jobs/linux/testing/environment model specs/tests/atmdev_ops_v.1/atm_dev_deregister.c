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
 * ee the License for the specific language governing permissions and
 * limitations under the License.
 */

#include <linux/module.h>
#include <linux/atmdev.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

struct atm_dev *ldv_dev;

static void ldv_close(struct atm_vcc *dev)
{
	ldv_invoke_callback();
}


static int ldv_open(struct atm_vcc *vcc)
{
	ldv_invoke_callback();
	return ldv_undef_int();
}

static struct atmdev_ops ldv_ops = {
	.open = & ldv_open,
	.close = & ldv_close
};

static int __init ldv_init(void)
{
	int flip_a_coin;
	unsigned long *flags = ldv_undef_ptr();

	flip_a_coin = ldv_undef_int();
	if (flip_a_coin) {
		ldv_register();
		ldv_dev = atm_dev_register("ldv", &ldv_ops, ldv_undef_int(), flags);
		if (!ldv_dev) {
			atm_dev_deregister(ldv_dev);
			ldv_deregister();
			return ldv_undef_int_negative();
		}
		ldv_deregister();
		return 0;
	}

	return 0;
}

static void __exit ldv_exit(void)
{
	/* nothing */
}

module_init(ldv_init);
module_exit(ldv_exit);