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

#include <ldv/verifier/nondet.h>
#include <ldv/linux/emg/test_model.h>


int registration(void)
{
    if (ldv_undef_int()) {
        ldv_register();
        return 0;
    }
    return ldv_undef_int_negative();
}

void deregistration(void)
{
    ldv_deregister();
}

void callback(void)
{
    ldv_invoke_callback();
}
