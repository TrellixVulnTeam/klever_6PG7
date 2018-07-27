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
#include <ldv-test.h>

static int __init ldv_init(void)
{
	int var1 = -10, var2 = -5, var3 = -2, var4 = -1, var5 = 0, var6 = 1,
	    var7 = 2, var8 = 5, var9 = 10;

	if (--var1 == -11 &&
	    --var2 == -6 &&
	    --var3 == -3 &&
	    --var4 == -2 &&
	    --var5 == -1 &&
	    --var6 == 0 &&
	    --var7 == 1 &&
	    --var8 == 4 &&
	    --var9 == 9)
		ldv_error();

	return 0;
}



module_init(ldv_init);
