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

#include <linux/sched.h>

static struct task_struct ldv_current;

/* This is a very rough model since for different processes there should be different PIDs as well as there may be other
   PIDs in addition to 1. Though EMG can properly model (get_)current, let's hope that this simple and static model will
   be enough for currently generated environment models and used verification tools. */
struct task_struct *ldv_get_current(void)
{
	/* TODO: CIF generates invalid code for Linux 4.15.18 if make this initialization globally. */
	ldv_current.pid = 1;
	return &ldv_current;
}
