#include <linux/module.h>
#include <verifier/nondet.h>
#include <linux/emg/test_model.h>
#include "ldvops.h"

void ldv_handler(struct ldv_resource *arg)
{
    ldv_invoke_reached();
}

static struct ldv_driver ops = {
	.handler = ldv_handler,
};

static int __init ldv_init(void)
{
	return ldv_driver_register(& ops);
}

module_init(ldv_init);
