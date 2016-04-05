#   Copyright (c) 2013-2015, University of Bern, Switzerland.
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

"""
Service Orchestrator for RCBaaS.
Version 2.0
"""

import os
import random
import requests
import threading
import time
import sys
from zabbix_api import ZabbixAPI
from zabbix_api_mio import APIConnector
from py4j.java_gateway import JavaGateway
from py4j.java_collections import SetConverter, MapConverter, ListConverter
import paramiko

from sdk.mcn import util
from sm.so import service_orchestrator
from sm.so.service_orchestrator import LOG
from sm.so.service_orchestrator import BUNDLE_DIR

import traceback

DEFAULT_REGION = 'RegionOne'
#zabbix_url='http://137.204.57.236:8008/zabbix/'
#zabbix_user='azanni'
#zabbix_pass='azanni'

#MAAS_DEFAULT_IP = '160.85.4.28'
#ZABBIX_URL='http://' + MAAS_DEFAULT_IP + '/zabbix/'
#ZABBIX_USER='admin'
#ZABBIX_PASS='zabbix'
zabbix_url='http://160.85.4.28/zabbix/'
zabbix_user='admin'
zabbix_pass='zabbix'
trigger_value=0.5

class MyList(list):
    def append(self, item):
        list.append(self, item)
        if len(self) > 5: self[:1]=[]

def getGreyModelValues(gateway, composedList):
    values = []
    for list_py in composedList:
        list_java = ListConverter().convert(list_py, gateway._gateway_client)
        nextValue = gateway.entry_point.nextValue(list_java)
        values.append(float("{0:.4f}".format(nextValue)))
    return values

class SOE(service_orchestrator.Execution):
    """
    SO execution part.
    """
    def __init__(self, token, tenant, ready_event):
        super(SOE, self).__init__(token, tenant)
        self.token = token
        self.tenant = tenant
        self.event = ready_event
        self.influxdb_ip = None
        self.updated = False
        self.endpoint = None
        self.maas_endpoint = None
        # Default topology
        self.layers = {}
        self.routers = {}
        self.stack_id = None
        self.stack_id_old = None
        self.deployer = util.get_deployer(self.token,
                                          url_type='public',
                                          tenant_name=self.tenant,
                                          region=DEFAULT_REGION)

    def design(self):
        """
        Do initial design steps here.
        """
        LOG.debug('Executing design logic')
        self.resolver.design()

    def deploy(self, attributes):
        """
        deploy RCBs.
        """
        LOG.debug('Deploy service dependencies')
        self.resolver.deploy()
        LOG.debug('Executing deployment logic')
        # Get template
        templ_file = open(os.path.join(BUNDLE_DIR, 'data', 'influxdb-cyclops.yaml'), 'r')
        self.graph = templ_file.read()
        # Deploy template
        if self.stack_id is None:
            self.stack_id = self.deployer.deploy(self.graph, self.token, \
                name='rcb_' + str(random.randint(1000, 9999)))

    def provision(self, attributes=None):
        """
        (Optional) if not done during deployment - provision.
        """
        self.resolver.provision()
        LOG.debug('RCB SO provision')

        LOG.debug('Executing resource provisioning logic')
        # XXX note that provisioning of external services must happen before resource provisioning
        # Get endpoint of MaaS
#        if attributes:
            #print attributes
#            if 'mcn.endpoint.maas' in attributes:
#                self.sm_parameters['maas_ip_address'] = attributes['mcn.endpoint.maas']
#                LOG.debug('Provision mcn.endpoint.maas in attributes'+ str(attributes['mcn.endpoint.maas']))

        # Update stack
        self.update(True)
        self.event.set()

    def dispose(self):
        """
        Dispose SICs.
        """
        LOG.info('Disposing of 3rd party service instances...')
        self.resolver.dispose()

        if self.stack_id is not None:
            LOG.info('Disposing of resource instances...')
            self.deployer.dispose(self.stack_id, self.token)
            self.endpoint = None
            self.maas_endpoint = None
            self.stack_id = None

    def state(self):
        """
        Report on state.
        """
        # TODO ideally here you compose what attributes should be returned to the SM
        # In this case only the state attributes are returned.
        # resolver_state = self.resolver.state()
        if self.stack_id is not None:
            LOG.info('stack id state: ' + str(self.stack_id))
            try:
                tmp = self.deployer.details(self.stack_id, self.token)
                LOG.info('###### : ' + str(tmp.get('output')))
                if tmp.get('output', None) is not None:
                    for output in tmp['output']:
                        if output['output_key'].startswith('mcn.endpoint.influxdb'):
                            influxdb_url = output['output_value']
                            self.influxdb_ip = influxdb_url.split(':')[1][2:]
                            print "influxdb_ip: ", self.influxdb_ip
                            LOG.debug('influxdb_ip: '+self.influxdb_ip)
                            break
                    LOG.debug('State: ' + tmp['state'] + ' len output =' + str(len(tmp['output'])))
                    return tmp['state'], self.stack_id, tmp['output']
                else:
                    return tmp['state'], self.stack_id, []
                    #return 'Unknown', 'N/A'
            except:
                LOG.debug(traceback.print_exc())
                LOG.debug('Error/Exception getting stack!')
                return 'Error', self.stack_id, []
        else:
            return 'Unknown', 'N/A', []

    def update(self, provisioning = False, attributes = None):
        """
        deploy updated SICs.
        """
        LOG.debug('Executing update deployment logic')
        # Check if attributes are being updated
        if attributes:
            if 'mcn.endpoint.maas' in attributes:
                self.maas_endpoint = str(attributes['mcn.endpoint.maas'])
        # Get new template
        templ_file = open(os.path.join(BUNDLE_DIR, 'data', 'influxdb-cyclops.yaml'), 'r')
        self.graph = templ_file.read()
        # Wait for any pending operation to complete
        while (True):
            if self.stack_id is not None:
                tmp = self.deployer.details(self.stack_id, self.token)
                if tmp['state'] == 'CREATE_COMPLETE' or tmp['state'] == 'UPDATE_COMPLETE':
                    break
                else:
                    time.sleep(10)
        # Deploy new template
        if self.stack_id is not None:
            self.deployer.update(self.stack_id, self.graph, self.token)
        # Mark as updated for SOD
        self.updated = True

    def notify(self, entity, attributes, extras):
        super(SOE, self).notify(entity, attributes, extras)
        # TODO here you can add logic to handle a notification event sent by the CC
        # XXX this is optional

class SOD(service_orchestrator.Decision, threading.Thread):
    """
    Decision part of SO.
    """
    def __init__(self, so_e, token, ready_event):
        super(service_orchestrator.Decision, self).__init__()
        self.so_e = so_e
        self.token = token
        self.event = ready_event
        self.hosts_cpu_load = []
        self.hosts_cpu_util = []
        #self.hosts_mem = []
        self.connector = APIConnector()
        self.auth = self.connector.auth_zabbix()
        gateway = JavaGateway()

    def run(self):
        """
        Decision part implementation goes here.
        """
        Tstart=time.time()
        #host_ids = connector.get_zbx_hostids()
        try:
            hostid = connector.host.get({"filter":{"host":"influxdb-vm"}})[0]["hostid"]
        except:
            print "WARNING: Hostname influxdb not found"
        try:
            item = "system.cpu.load[percpu,avg1]"
            value = connector.item.get({"output":"extend","hostids":hostid,"filter":{"key_":item}})[0]["lastvalue"]
            print value
        except:
            pass

        # for host in host_ids:
        self.hosts_cpu_load.append(MyList())
        self.hosts_cpu_util.append(MyList())
        #hosts_mem.append(MyList())

        Tconfig=time.time()-Tstart
        print "Config time: ", Tconfig, "s"
        while True:
            LOG.debug('Waiting for deploy and provisioning to finish')
            self.event.wait()
            LOG.debug('Starting runtime logic...')
            # Decision logic
            # Until service instance is destroyed
            while self.so_e.stack_id is not None:
                # Check if update is complete
                while True:
                    #tmp = self.so_e.deployer.details(self.so_e.stack_id, self.so_e.token)
                    tmp = self.so_e.state()
                    if tmp[0] == 'UPDATE_COMPLETE':
                        break
                    else:
                        time.sleep(10)
                # Set updated back to False
                self.so_e.updated = False
                # Update the information about CCNx routers
                self.so_e.state()
                # Monitor the resources
                self.monitoring()
            self.event = ready_event 

    def monitoring(self):
        Tzbx_start=time.time()
        cpu_loads = self.connector.get_cpu_load()
        cpu_util = self.connector.get_cpu_util()
        #mem = connector.get_mem_load()
        #for i in range(len(host_ids)):
        self.hosts_cpu_load[0].append(cpu_loads[0])
        self.hosts_cpu_util[0].append(cpu_util[0])
        #hosts_mem[i].append(mem[i])
        print "zbx - cpu_load: ", self.hosts_cpu_load
        print "zbx - cpu_util: ", self.hosts_cpu_util
        #print "zbx - mem: ", hosts_mem

        Tzbx=time.time()-Tzbx_start
        print "Zbx time to read: ", Tzbx, "s"

        if len(self.hosts_cpu_load[0]) > 0:
            Tgm_start=time.time()

            cpu_load_GM = self.hosts_cpu_load#getGreyModelValues(self.gateway, hosts_cpu_load)
            cpu_util_GM = self.hosts_cpu_util#getGreyModelValues(self.gateway, hosts_cpu_util)
            #mem_GM = 5#getGreyModelValues(self.gateway, hosts_mem)
            print "next value GM - cpu_load: ", cpu_load_GM
            print "next value GM - cpu_util: ", cpu_util_GM
            #print "next value GM - mem: ", mem_GM

            #avg=reduce(lambda x, y: x + y, cpu_load_GM)/len(cpu_load_GM)
            avg=20
            print avg
            if avg > trigger_value:
                print "Trigger activated. I'm going to move the VM state."
                try:
                    Tmovetot_start=time.time()

                    #MIGRATION
                    # Deploy template
                    #if self.stack_id is None:
                    #    self.stack_id = self.deployer.deploy(self.graph, self.token, name='rcb_' + str(random.randint(1000, 9999)))
                    self.so_e.stack_id_old = self.so_e.stack_id
                    self.so_e.influxdb_ip_old = self.so_e.influxdb_ip
                    print "before - self.so_e.stack_id: ", self.so_e.stack_id
        #            self.so_e.stack_id=None
        #            self.so_e.deploy(None)
        #            self.so_e.provision()
                    print "after - self.so_e.stack_id: ", self.so_e.stack_id
        #            while True:
        #                tmp = self.so_e.state()
        #                if tmp[0] == 'UPDATE_COMPLETE':
        #                    break
        #                else:
        #                    time.sleep(10)

                    #move data -> 
                    print "I'm moving data from old influxVM to new influxVM",  self.so_e.influxdb_ip_old, self.so_e.influxdb_ip
                    if not self.so_e.influxdb_ip_old or not self.so_e.influxdb_ip:
                        print "Cannot move data. Missing IP"
                        print "old VM ip: ", self.so_e.influxdb_ip_old
                        print "new VM ip: ", self.so_e.influxdb_ip
                    else:
                        print "I'm moving data..."
                        #ssh = paramiko.SSHClient()
                        #ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                        #ssh.connect(self.so_e.influxdb_ip, username='ubuntu', key_filename=BUNDLE_DIR+'/key/mcn-key.pem')
                        #command = 'bash /home/ubuntu/greyModel_noCluster/database_config.sh ' + self.so_e.influxdb_ip_old
                        #stdin, stdout, stderr = ssh.exec_command(command)
                        #print "Script output", stdout.readlines()
                        #ssh.close()
                        print "Data moved"
                    Tmovetot=time.time()-Tmovetot_start
                    print "Total time to migrate the VMs: ", Tmovetot, "s"

         #           stack_current = self.so_e.stack_id
         #           self.so_e.stack_id = self.so_e.stack_id_old
         #           self.so_e.dispose()
         #           self.so_e.stack_id = stack_current

                except:
                    print "Cannot move VM. Unexpected error:", sys.exc_info()[0]
                    raise
        print "Now I sleep..."
        time.sleep(10)

class ServiceOrchestrator(object):
    """
    RCBaaS SO.
    """

    def __init__(self, token, tenant):
        # this python thread event is used to notify the SOD that the runtime phase can execute its logic
        self.event = threading.Event()
        self.so_e = SOE(token=token, tenant=tenant, ready_event=self.event)
        self.so_d = SOD(so_e=self.so_e, token=token, ready_event=self.event)
        LOG.debug('Starting SOD thread...')
        self.so_d.start()
