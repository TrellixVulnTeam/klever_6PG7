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

#include <linux/types.h>
#include <ldv/linux/common.h>
#include <ldv/verifier/common.h>
#include <ldv/verifier/nondet.h>

int ldv_dma_calls = 0;

dma_addr_t ldv_dma_map_page(void) {
	if (ldv_dma_calls != 0)
		/* ASSERT Check that previous dma_mapping call was checked */
		ldv_assert();

	/* NOTE Increase map counter */
	ldv_dma_calls++;

	return ldv_undef_int();
}

int ldv_dma_mapping_error(void) {
	if (ldv_dma_calls <= 0)
		/* ASSERT No dma_mapping calls to verify */
		ldv_assert();

	ldv_dma_calls--;

	return ldv_undef_int();
}

dma_addr_t ldv_dma_map_single(void) {
	if (ldv_dma_calls != 0)
		/* ASSERT Check that previous dma_mapping call was checked */
		ldv_assert();

	/* NOTE Increase map counter */
	ldv_dma_calls++;

	return ldv_undef_int();
}

dma_addr_t ldv_dma_map_single_attrs(void) {
	if (ldv_dma_calls != 0)
		/* ASSERT Check that previous dma_mapping call was checked */
		ldv_assert();

	/* NOTE Increase map counter */
	ldv_dma_calls++;

	return ldv_undef_int();
}

void ldv_check_final_state(void) {
	if (ldv_dma_calls != 0)
		/* ASSERT All dma_mapping calls should be checked before module unloading */
		ldv_assert();
}
