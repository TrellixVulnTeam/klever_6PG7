#include <linux/module.h>

static int __init init(void)
{
	struct module *test_module_1;
	struct module *test_module_2;

	__module_get(test_module_1);
	__module_get(test_module_2);
	if (module_refcount(test_module_1) == 2)
	{
		module_put(test_module_1);
		module_put(test_module_2);
	}
	return 0;
}

module_init(init);