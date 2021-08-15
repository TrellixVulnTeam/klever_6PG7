/*
 * Copyright (c) 2021 ISP RAS (http://www.ispras.ru)
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
#include <ldv/common/test.h>
#include <ldv/verifier/memory.h>

struct ldv_struct1 {
	int field1;
	int field2;
};
struct ldv_struct2 {
	int field1;
	struct ldv_struct1 field2;
	int field3;
};
struct ldv_struct2 ldv_var = {1, {2, 3}, 4};

static int __init ldv_init(void)
{
	struct ldv_struct2 var;

	if (ldv_var.field1 != 1 ||
	    ldv_var.field2.field1 != 2 ||
	    ldv_var.field2.field2 != 3 ||
	    ldv_var.field3 != 4)
		ldv_unexpected_error();

	memcpy(&var, &ldv_var, sizeof(var));

	if (var.field1 != 1 ||
	    var.field2.field1 != 2 ||
	    var.field2.field2 != 3 ||
	    var.field3 != 4)
		ldv_unexpected_error();

	return 0;
}

module_init(ldv_init);
