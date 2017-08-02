#include <linux/module.h>
#include <linux/netdevice.h>
#include <linux/emg/test_model.h>
#include <verifier/nondet.h>

struct net_device dev;
struct mutex *ldv_envgen;
int flip_a_coin;

static netdev_tx_t ldv_xmit(struct sk_buff *skb, struct net_device *dev)
{
    ldv_invoke_middle_callback();
    return 0;
}

static int ldv_open(struct net_device *dev)
{
	int res;

    ldv_invoke_callback();
    res = ldv_undef_int();
    if (!res)
        ldv_probe_up();
    return res;
}

static int ldv_close(struct net_device *dev)
{
	ldv_release_down();
    ldv_invoke_callback();
}

static const struct net_device_ops ldv_ops = {
	.ndo_open	= ldv_open,
	.ndo_stop	= ldv_close,
	.ndo_start_xmit = ldv_xmit,
};

static int __init ldv_init(void)
{
	flip_a_coin = ldv_undef_int();
    if (flip_a_coin) {
        dev.netdev_ops = &ldv_ops;
        ldv_register();
        return register_netdev(&dev);
    }
    return 0;
}

static void __exit ldv_exit(void)
{
	if (flip_a_coin) {
        unregister_netdev(&dev);
        ldv_deregister();
    }
}

module_init(ldv_init);
module_exit(ldv_exit);