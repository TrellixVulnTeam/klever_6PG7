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
#include <linux/tty_driver.h>
#include <ldv/linux/emg/test_model.h>
#include <ldv/verifier/nondet.h>
#include <ldv/verifier/common.h>

int disc;

int ldv_open(struct tty_struct * tty)
{
	ldv_invoke_reached();
	ldv_store_resource1(tty);
	return 0;
}

void ldv_close(struct tty_struct * tty)
{
	ldv_invoke_reached();
	ldv_check_resource1(tty);
}

static struct tty_ldisc_ops ldv_tty_ops = {
	.open = ldv_open,
	.close = ldv_close
};

static int __init ldv_init(void)
{
	disc = ldv_undef_int();
	return tty_register_ldisc(disc, & ldv_tty_ops);
}

static void __exit ldv_exit(void)
{
	int ret = tty_unregister_ldisc(disc);
	ldv_assume(!ret);
}

module_init(ldv_init);
module_exit(ldv_exit)

MODULE_LICENSE("GPL");
