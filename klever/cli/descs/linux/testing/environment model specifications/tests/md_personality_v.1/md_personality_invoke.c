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
#include "../drivers/md/md.h"
#include <ldv/linux/emg/test_model.h>
#include <ldv/verifier/nondet.h>

static int ldv_run(struct mddev *mddev)
{
	ldv_invoke_reached();
	ldv_store_resource1(mddev);
	return 0;
}

static void md_free(struct mddev *mddev, void *priv)
{
	ldv_invoke_reached();
	ldv_check_resource1(mddev);
}

static struct md_personality ldv_personality =
{
	.name		= "ldv",
	.run		= ldv_run,
	.free		= md_free,
};

static int __init ldv_init(void)
{
	ldv_invoke_test();
	return register_md_personality(&ldv_personality);
}

static void __exit ldv_exit(void)
{
	unregister_md_personality(&ldv_personality);
}

module_init(ldv_init);
module_exit(ldv_exit)

MODULE_LICENSE("GPL");
