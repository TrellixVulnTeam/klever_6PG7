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
#include <linux/interrupt.h>
#include <linux/irqreturn.h>
#include <ldv/linux/emg/test_model.h>
#include <ldv/verifier/nondet.h>

unsigned int irq_id = 100;
unsigned long irqflags;
void *data;
struct device *dev;

static irqreturn_t irq_handler(int irq_id, void * data)
{
	ldv_invoke_reached();
	ldv_check_irq(irq_id);
	ldv_check_resource1(data);
	return IRQ_WAKE_THREAD;
}

static irqreturn_t irq_thread(int irq_id, void * data)
{
	ldv_check_irq(irq_id);
	ldv_check_resource1(data);
	return IRQ_HANDLED;
}

static int __init ldv_init(void)
{
	ldv_invoke_test();
	data = ldv_undef_ptr();
	dev = ldv_undef_ptr();
	ldv_store_irq(irq_id);
	ldv_store_resource1(data);
	return devm_request_threaded_irq(dev, irq_id,irq_handler, irq_thread, irqflags, "ldv interrupt", data);
}

static void __exit ldv_exit(void)
{
	devm_free_irq(dev, irq_id, data);
}

module_init(ldv_init);
module_exit(ldv_exit)

MODULE_LICENSE("GPL");
