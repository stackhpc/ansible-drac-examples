#!/usr/bin/env python

# Copyright (c)2016 StackHPC Ltd
# Written by Stig Telfer, StackHPC Ltd
# OpenStack Ironic dynamic node inventory for Ansible
#
# Using the Ironic client library, retrieve state about all enrolled
# Ironic nodes and transform Ironic's node database into 
# Ansible dynamic inventory.
#
# This module is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This software is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this software.  If not, see <http://www.gnu.org/licenses/>.

import argparse
import os
import sys
import json
import logging

import os_client_config
from ironicclient import client as ironic

def ansible_data(node):
    if node.driver in ["pxe_ipmitool", "agent_ipmitool"]:
        node_ip = node.driver_info['ipmi_address']
    else:
        node_ip = "127.0.0.1"

    result = { 'ansible_ssh_host': node_ip,
               'ansible_connection': 'local',
               'ironic':
                { 'uuid': node.uuid,
                  'name': node.name,
                  'driver': node.driver,
                  'maintenance': node.maintenance,
                  'provision_state': node.provision_state,
                  'power_state': node.power_state, 
                  'driver_info': node.driver_info,
                  'properties': node.properties,
                  'instance_uuid': node.instance_uuid } }
    return result

def extract_profile(node):
    '''Extract capability attributes conventionally assigned by TripleO'''
    capabilities = node['ironic']['properties'].get('capabilities', None)
    for cap in capabilities.split(","):
        cap_kv = cap.split(':')
        if len(cap_kv) == 2 and cap_kv[0] == 'profile':
            return cap_kv[1]
    return None

def extract_maintenance(node):
    '''Return current maintenance mode as "true" or "false"'''
    return "true" if node['ironic']['maintenance'] else "false"

def extract_provision(node):
    '''Return current node provisioning state'''
    return node['ironic']['provision_state']

def extract_nodename(node):
    '''Return node human-friendly name'''
    return node['ironic']['name']

def collate_by(nodes, key_prefix, val_fn, result, always=[]):
    '''Given the node object list, apply an extractor method to each
       node to generate a new slicing-and-dicing of node state'''
    # Iterate the Ironic node objects with the user-supplied extractor function
    collate = {}
    for node in nodes:
        val = nodes[node]
        val_key = val_fn(val)
        if val_key is not None:
            node_uuid = val['ironic']['uuid']
            if val_key not in collate:
                collate[val_key] = [node_uuid]
            else:
                collate[val_key].append(node_uuid)

    # Enter the values found by collation of data extracted from Ironic objects
    for key_item in collate:
        key = key_prefix + key_item
        result[key] = collate[key_item]

    # Ensure any missing entries that must always be present are created empty
    for key_item in always:
        key = key_prefix + key_item
        if key not in result:
            result[key] = []


def parse_args():
    parser = argparse.ArgumentParser(description='OpenStack Inventory Module')
    parser.add_argument('--private',
                        action='store_true',
                        help='Use private address for ansible host')
    parser.add_argument('--debug', action='store_true', default=False,
                        help='Enable debug output')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--list', action='store_true',
                       help='List active Ironic nodes')
    group.add_argument('--host', help='Details for a specific Ironic node')

    return parser.parse_args()

def main():
    args = parse_args()

    # Configure logging to a file (including URLlib warnings...)
    if args.debug:
        logging.basicConfig(level=logging.DEBUG)
        logging.captureWarnings(True)

    # Check that we have environment rc settings for OpenStack access
    try:
        os_username = os.environ['OS_USERNAME']
        os_password = os.environ['OS_PASSWORD']
        os_auth_url = os.environ['OS_AUTH_URL']
        os_tenant_name = os.environ['OS_TENANT_NAME']
    except KeyError:
        print "Unable to read OpenStack environment, require: OS_USERNAME, OS_PASSWORD, OS_AUTH_URL and OS_TENANT_NAME"
        sys.exit(-1)

    # Extract data via the Ironic API
    client_api_version = '1'
    try:
        IRONIC = ironic.get_client(client_api_version,
                                   os_username=os_username,
                                   os_password=os_password,
                                   os_auth_url=os_auth_url, 
                                   os_tenant_name=os_tenant_name)
    except e:
        print "Error connecting to Ironic: %s" % (e)
        sys.exit(-1)

    if args.list:
        nodes = IRONIC.node.list()
        hostvars = { node.uuid: ansible_data(IRONIC.node.get(node.uuid)) for node in nodes }
    else:
        node = IRONIC.node.get(args.host)
        hostvars = { node.uuid: ansible_data(node) }

    # Transform the data returned into a format usable as inventory by Ansible
    result = { "_meta": { "hostvars": hostvars }, "": hostvars.keys() }
    collate_by(hostvars, "capability_profile_", extract_profile, result)
    collate_by(hostvars, "maintenance_", extract_maintenance, result, always=["true", "false"] )
    collate_by(hostvars, "provision_", extract_provision, result, always=["available", "active"] )
    collate_by(hostvars, "node_", extract_nodename, result)

    # Emit
    print json.dumps(result, sort_keys=True, indent=2)


if __name__ == '__main__':
    main()
