# Copyright (c) 2020 ISP RAS (http://www.ispras.ru)
# Ivannikov Institute for System Programming of the Russian Academy of Sciences
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import errno
import os
import re
import sys

import keystoneauth1.identity
import keystoneauth1.session
import glanceclient.client
import keystoneauth1.exceptions
import novaclient.client
import novaclient.exceptions
import neutronclient.v2_0.client
import cinderclient.client

from klever.deploys.utils import get_password


class OSClient:
    GLOBAL_NET_TYPE = {'internal': 'ispras', 'external': 'external_network'}
    NET_TYPE = {'internal': 'net-for-intra-computations', 'external': 'net-for-83.149.198-computations'}

    def __init__(self, args, logger):
        self.args = args
        self.logger = logger
        self.kind = args.entity
        self.password_file = os.path.join(os.path.expanduser('~'), '.config', 'klever', 'openstack')

        session = self.__get_session()

        self.logger.info('Initialize OpenStack clients')
        self.glance = glanceclient.client.Client('2', session=session)
        self.nova = novaclient.client.Client('2', session=session)
        self.neutron = neutronclient.v2_0.client.Client(session=session)
        self.cinder = cinderclient.client.Client('3', session=session)

    def __getattr__(self, name):
        self.logger.error(f'Action "{name}" is not supported for "{self.kind}"')
        sys.exit(errno.ENOSYS)

    def image_exists(self, image_name):
        return self.get_images(image_name) != []

    def get_base_image(self, base_image_name):
        self.logger.info(f'Get base image matching "{base_image_name}"')

        base_images = self.get_images(base_image_name)

        if len(base_images) == 0:
            self.logger.error(f'There are no base images matching "{base_image_name}"')
            sys.exit(errno.EINVAL)

        if len(base_images) > 1:
            self.logger.error(
                f'There are several base images matching "{base_image_name}", please, resolve this conflict manually'
            )
            sys.exit(errno.EINVAL)

        return base_images[0]

    def get_images(self, image_name):
        images = []

        for image in self.glance.images.list():
            if re.fullmatch(image_name, image.name):
                images.append(image)

        return images

    def show_instance(self, instance):
        return f'{instance.name} (status: {instance.status}, IP: {self.get_instance_floating_ip(instance, exit_on_error=False)})'

    def instance_exists(self, instance_name):
        return self.get_instances(instance_name) != []

    def get_instance(self, instance_name):
        self.logger.info(f'Get instance matching "{instance_name}"')

        instances = self.get_instances(instance_name)

        if len(instances) == 0:
            self.logger.error(f'There are no intances matching "{instance_name}"')
            sys.exit(errno.EINVAL)

        if len(instances) > 1:
            self.logger.error(
                f'There are several instances matching "{instance_name}", please, resolve this conflict manually'
            )
            sys.exit(errno.EINVAL)

        return instances[0]

    def get_instances(self, instance_name):
        instances = []

        for instance in self.nova.servers.list():
            if re.fullmatch(instance_name, instance.name):
                instances.append(instance)

        return instances

    def get_instance_floating_ip(self, instance, exit_on_error=True):
        floating_ip = None
        for network_addresses in instance.addresses.values():
            for address in network_addresses:
                if address.get('OS-EXT-IPS:type') == 'floating':
                    floating_ip = address.get('addr')
                    break
            if floating_ip:
                break

        if not floating_ip and exit_on_error:
            self.logger.error('There are no floating IPs for instance {instance.name}, please, resolve this manually')
            sys.exit(errno.EINVAL)
        elif not floating_ip:
            return "NOT FOUND"

        return floating_ip

    def assign_floating_ip(self, instance, share=False):
        if share:
            network_name = self.GLOBAL_NET_TYPE["external"]
        else:
            network_name = self.GLOBAL_NET_TYPE["internal"]

        floating_ip = None
        network_id = self.get_network_id(network_name)

        for f_ip in self.neutron.list_floatingips()['floatingips']:
            if f_ip['status'] == 'DOWN' and f_ip['floating_network_id'] == network_id:
                floating_ip = f_ip
                break

        if not floating_ip:
            floating_ip = self.neutron.create_floatingip(
                {"floatingip": {"floating_network_id": network_id}}
            )['floatingip']

        port = self.neutron.list_ports(device_id=instance.id)['ports'][0]
        self.neutron.update_floatingip(floating_ip['id'], {'floatingip': {'port_id': port['id']}})

        self.logger.info('Floating IP {0} is attached to instance "{1}"'
                         .format(floating_ip['floating_ip_address'], instance.name))

        return floating_ip

    def interface_detach(self, instance):
        ports = self.neutron.list_ports(device_id=instance.id)['ports']

        if len(ports) == 0:
            self.logger.info(f'Instance "{instance.name}" has no networks attached')
            return

        for port in ports:
            instance.interface_detach(port['id'])
            network_name = self.get_network_name(port["network_id"])
            self.logger.info(f'Network "{network_name}" is dettached from instance "{instance.name}"')

    def interface_attach(self, instance, share=False):
        if share:
            network_name = self.NET_TYPE["external"]
        else:
            network_name = self.NET_TYPE["internal"]

        network_id = self.get_network_id(network_name)
        instance.interface_attach(port_id=None, net_id=network_id, fixed_ip=None)

        self.logger.info(f'Network "{network_name}" is attached to instance "{instance.name}"')

    def get_network_id(self, network_name):
        for net in self.neutron.list_networks()['networks']:
            if net['name'] == network_name:
                return net['id']

        self.logger.error(f'OpenStack does not have network with "{network_name}" name')
        sys.exit(errno.EINVAL)

    def get_network_name(self, network_id):
        for net in self.neutron.list_networks()['networks']:
            if net['id'] == network_id:
                return net['name']

        self.logger.error(f'OpenStack does not have network with "{network_id}" id')
        sys.exit(errno.EINVAL)

    def __get_session(self):
        self.logger.info('Sign in to OpenStack')
        try:
            with open(self.password_file, 'r') as fp:
                password = fp.read()
            self.logger.info(f'Use password from "{self.password_file}" file')
        except Exception:
            password = get_password(self.logger, 'OpenStack password for authentication: ')

        auth = keystoneauth1.identity.v3.Password(
            auth_url=self.args.os_auth_url,
            username=self.args.os_username,
            password=password,
            user_domain_name=self.args.os_domain_name,
            project_domain_name=self.args.os_domain_name,
            project_name=self.args.os_tenant_name,
        )
        session = keystoneauth1.session.Session(auth=auth)

        if not os.path.isfile(self.password_file) and self.args.store_password:
            self.logger.info(f'Your password is now stored in plain text in "{self.password_file}" file')

            os.makedirs(os.path.dirname(self.password_file), exist_ok=True)
            with open(self.password_file, 'w') as fp:
                fp.write(password)

        try:
            # Perform a request to OpenStack in order to check the correctness of provided username and password.
            session.get_auth_headers()
        except keystoneauth1.exceptions.http.Unauthorized:
            self.logger.error('Sign in failed: invalid username or password')
            sys.exit(errno.EACCES)

        return session
