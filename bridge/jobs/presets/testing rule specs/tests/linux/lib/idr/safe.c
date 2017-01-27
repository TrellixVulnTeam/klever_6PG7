/*
 * Copyright (c) 2014-2016 ISPRAS (http://www.ispras.ru)
 * Institute for System Programming of the Russian Academy of Sciences
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
#include <linux/idr.h>

DEFINE_IDR(idp3);

int __init my_init(void)
{
	struct idr *idp, *idp2;
	void *ptr, *found;
	int start, end;
	gfp_t gfp_mask;

	idr_init(idp);
	idr_init(idp2);
	idr_alloc(idp, ptr, start, end, gfp_mask);
	found = idr_find(idp, end);
	idr_remove(idp, end);
	idr_alloc(idp, ptr, start, end, gfp_mask);
	found = idr_find(idp, end);
	idr_remove(idp, end);
	idr_destroy(idp);

	idr_alloc(idp2, ptr, start, end, gfp_mask);
	found = idr_find(idp2, end);
	idr_remove(idp2, end);
	idr_alloc(idp2, ptr, start, end, gfp_mask);
	found = idr_find(idp2, end);
	idr_remove(idp2, end);
	idr_destroy(idp2);

	idr_destroy(&idp3);

	return 0;
}

module_init(my_init);
