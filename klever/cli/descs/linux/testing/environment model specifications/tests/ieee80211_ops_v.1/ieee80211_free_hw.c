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
#include <net/mac80211.h>
#include <ldv/linux/emg/test_model.h>
#include <ldv/verifier/nondet.h>

struct ieee80211_hw *priv;

static int ldv_start_callback(struct ieee80211_hw *hw)
{
	ldv_invoke_callback();
	ldv_store_resource1(hw);
	return 0;
}

static void ldv_stop_callback(struct ieee80211_hw *hw)
{
	ldv_invoke_callback();
	ldv_check_resource1(hw, 1);
}

static const struct ieee80211_ops ldv_ops = {
	.start			= ldv_start_callback,
	.stop			= ldv_stop_callback
};

static int __init ldv_init(void)
{
	int flip_a_coin;

	flip_a_coin = ldv_undef_int();
	if (flip_a_coin) {
		ldv_register();
		priv = ieee80211_alloc_hw(sizeof(struct ieee80211_ops), &ldv_ops);
		if (priv) {
			ieee80211_free_hw(priv);
			ldv_deregister();
			return ldv_undef_int_negative();
		}
		ldv_deregister();
	}
	return 0;
}

static void __exit ldv_exit(void)
{
	/* pass */
}

module_init(ldv_init);
module_exit(ldv_exit)

MODULE_LICENSE("GPL");
