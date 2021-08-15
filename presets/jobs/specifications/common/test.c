/*
 * Copyright (c) 2019 ISP RAS (http://www.ispras.ru)
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

#include <ldv/common/test.h>

void ldv_expected_error(void)
{
	/* ASSERT Expected error */
	ldv_assert();
}

void ldv_unexpected_error(void)
{
	/* ASSERT Unexpected error */
	ldv_assert();
}

void ldv_expected_memory_safety_error(void)
{
	int *var = (void *)0;
	/* ASSERT Expected memory safety error */
	*var;
}

void ldv_unexpected_memory_safety_error(void)
{
	int *var = (void *)0;
	/* ASSERT Unexpected memory safety error */
	*var;
}
