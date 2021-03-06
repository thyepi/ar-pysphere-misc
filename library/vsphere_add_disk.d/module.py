#!/usr/bin/python
# -*- coding: utf-8 -*-

# (c) 2014, <t.delamare@epiconcept.fr>
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

DOCUMENTATION = '''
#include documentation.yml
'''

EXAMPLES = '''
#include examples.yml
'''

import sys
try:
    import pysphere
    from pysphere import VIServer, VITask
    from pysphere.resources import VimService_services as VI
except ImportError:
    print "failed=True msg='pysphere python module unavailable'"
    sys.exit(1)

import ssl

def main():

    module = AnsibleModule(
        argument_spec = dict(
            vcenter_hostname = dict(required=True, aliases=['vcenter']),
            username = dict(required=True, aliases=['user']),
            password = dict(required=True),
            guest = dict(required=True),
            validate_certs=dict(required=False, type='bool', default=True),
            disk = dict(required=True, aliases=['unit']),
            size = dict(required=True)
        ),
        supports_check_mode=True
    )

    host = module.params.get('vcenter_hostname')
    login = module.params.get('username')
    password = module.params.get('password')
    guest = module.params.get('guest')
    validate_certs = module.params['validate_certs']
    disk_unit = int(module.params.get('disk'))
    disk_size = int(module.params.get('size'))

    if disk_unit < 1 or disk_unit > 4:
        module.fail_json(msg='Dubious disk unit')

    if disk_size < 2 or disk_size > 2000:
        module.fail_json(msg='Dubious disk size')
        
    server = VIServer()
    if not validate_certs:
        default_context = ssl._create_default_https_context
        ssl._create_default_https_context = ssl._create_unverified_context
    try:
        server.connect(host, login, password)
    except Exception, e:
        module.fail_json(msg='Failed to connect to %s: %s' % (host, e))

    # Check if the VM exists before continuing    
    try:
        vm = server.get_vm_by_name(guest)
    except pysphere.resources.vi_exception.VIException, e:
        module.fail_json(msg=e.message)

    # get disks info
    disks = [d for d in vm.properties.config.hardware.device
             if d._type=='VirtualDisk'
             and d.backing._type in ['VirtualDiskFlatVer1BackingInfo',
                                     'VirtualDiskFlatVer2BackingInfo',
                                     'VirtualDiskRawDiskMappingVer1BackingInfo',
                                     'VirtualDiskSparseVer1BackingInfo',
                                     'VirtualDiskSparseVer2BackingInfo'
                                     ]]

    vsphere_disks_info = {}
    for disk in disks:
        unit = disk.unitNumber
        vsphere_disks_info[unit] = {
            'label': disk.deviceInfo.label,
            'summary': disk.deviceInfo.summary,
            'mode': disk.backing.diskMode,
            'type': disk.backing._type,

            'unit': disk.unitNumber,
            'key': disk.key,
            'capacity': disk.capacityInKB,
            'file': disk.backing.fileName,
            }

    facts = { 'vsphere_disks_info': vsphere_disks_info }
    
    # Check if disk exists
    if disk_unit in vsphere_disks_info:
        size = int(vsphere_disks_info[disk_unit]['capacity']) >> 20
        if size != disk_size:
            module.fail_json(
                msg="Disk unit {} already exist, but with a different size ({}G)"
                .format(disk_unit, size))
        module.exit_json(changed=False, ansible_facts = facts)

    # do nothing if in dry mode
    if module.check_mode:
        module.exit_json(changed = True, ansible_facts = facts)

    request = VI.ReconfigVM_TaskRequestMsg()
    _this = request.new__this(vm._mor)
    _this.set_attribute_type(vm._mor.get_attribute_type())
    request.set_element__this(_this)

    spec = request.new_spec()

    disk_spec = spec.new_deviceChange()
    disk_spec.Operation = "add"
    disk_spec.FileOperation = "create"

    hd = VI.ns0.VirtualDisk_Def("hd").pyclass()
    hd.Key = -100
    hd.UnitNumber = int(disk_unit)
    hd.CapacityInKB = int(disk_size) << 20
    hd.ControllerKey = 1000

    backing = VI.ns0.VirtualDiskFlatVer2BackingInfo_Def("backing").pyclass()
    data = vm.get_properties()
    path = "%s" % data['path']
    p = re.compile(r"\[([\w-]+)\] ")
    try:
        m = p.match(path)
    except re.error, e:
        print e
        sys.exit(1)
    datastore_name = m.group(1)
    backing.FileName = "[%s]" % datastore_name
    backing.DiskMode = "persistent"
    backing.Split = False
    backing.WriteThrough = False
    backing.ThinProvisioned = False
    backing.EagerlyScrub = False
    hd.Backing = backing

    disk_spec.Device = hd

    spec.DeviceChange = [disk_spec]
    request.Spec = spec

    task = server._proxy.ReconfigVM_Task(request)._returnval
    vi_task = VITask(task, server)

    # Wait for task to finish
    status = vi_task.wait_for_state([vi_task.STATE_SUCCESS,
                                     vi_task.STATE_ERROR])

    if status == vi_task.STATE_ERROR:
        msg = "ERROR CONFIGURING VM: " + vi_task.get_error_message()
        module.fail_json(msg=msg)

    module.exit_json(changed = True, ansible_facts = facts)

# this is magic, see lib/ansible/module_common.py
#<<INCLUDE_ANSIBLE_MODULE_COMMON>>
main()
