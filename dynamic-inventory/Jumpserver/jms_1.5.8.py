#!/usr/bin/env python
# -*- coding: utf-8 -*-

import yaml
import os
import sys
import argparse
import requests
import json

CONFIG_FILES = ['/etc/jumpserver/jms.yml', '/etc/ansible/jms.yml']
URL_AUTH = '%s/api/v1/authentication/auth/'
URL_NODES = '%s/api/v1/assets/nodes/'
URL_NODES_CHILD = '%s/api/v1/assets/nodes/%s/children/'
URL_NODES_ASSETS = '%s/api/v1/assets/nodes/%s/assets/'
URL_SYS_ASSETS_RELATIONS = '%s/api/v1/assets/system-users-assets-relations/'
URL_SYS_AUTH = '%s/api/v1/assets/system-user/%s/auth-info/'


class JumpserverInventory(object):

    def read_settings(self):
        config_files = CONFIG_FILES
        # 当前执行路径下的jms.yml也会匹配
        config_files.append(os.path.dirname(os.path.realpath(__file__)) + '/jms.yml')
        config = None
        for cfg_file in config_files:
            if os.path.isfile(cfg_file):
                stream = open(cfg_file, 'r')
                config = yaml.safe_load(stream)
                break
        if not config:
            sys.stderr.write('No config file found at {0}\n'.format(config_files))
            sys.exit(1)

        # login info
        self.jms_server = config['jumpserver']['auth']['host']
        self.jms_username = config['jumpserver']['auth']['user']
        self.jms_password = config['jumpserver']['auth']['password']

    @staticmethod
    def read_cli():
        parser = argparse.ArgumentParser()
        parser.add_argument('--host')
        parser.add_argument('--list', action='store_true')
        return parser.parse_args()

    @staticmethod
    def hoststub():
        return {
            "hosts": [],
            "children": []
        }

    def get_list(self, token):
        # data = {'_meta': {'hostvars': {}}}
        data = dict(_meta=dict(hostvars=dict()))
        # 保存asset id和主机名对应关系字典
        assets_data = dict()
        assets_isactive = dict()
        temp_hostvars = dict()

        url_node = URL_NODES % self.jms_server
        header_info = {"Authorization": 'Bearer ' + token}
        response = requests.get(url_node, headers=header_info)
        nodes_data = json.loads(response.text)
        for node in nodes_data:
            node_id = node['id']
            node_value = node['value']
            url_node_child = URL_NODES_CHILD % (self.jms_server, node_id)
            response = requests.get(url_node_child, headers=header_info)
            node_child_data = json.loads(response.text)

            # hosts和children是list列表，其余默认为dict类型。
            if node_value not in data:
                data[node_value] = self.hoststub()
            for node_child in node_child_data:
                data[node_value]['children'].append(node_child['value'])
            url_node_assets = URL_NODES_ASSETS % (self.jms_server, node_id)
            response = requests.get(url_node_assets, headers=header_info)
            node_assets_data = json.loads(response.text)
            for node_assets in node_assets_data:
                assets_isactive[node_assets['id']] = node_assets['is_active']
                if node_assets['is_active']:
                    hostname = node_assets['hostname']
                    assets_data[node_assets['id']] = hostname
                    data[node_value]['hosts'].append(hostname)
                    # 初始化字典项
                    temp_hostvars[hostname] = dict()
                    temp_hostvars[hostname]['ansible_host'] = node_assets['ip']
                    temp_hostvars[hostname]['ansible_port'] = node_assets['protocols'][0].split('/')[1]

        url_sys_assets_relations = URL_SYS_ASSETS_RELATIONS % self.jms_server
        response = requests.get(url_sys_assets_relations, headers=header_info)
        sys_assets_data = json.loads(response.text)
        for sys_assets_relation in sys_assets_data:
            sys_users_id = sys_assets_relation['systemuser']
            assets_id = sys_assets_relation['asset']
            if assets_isactive[assets_id]:
                url_sys_assets_relations = URL_SYS_AUTH % (self.jms_server, sys_users_id)
                response = requests.get(url_sys_assets_relations, headers=header_info)
                sys_auth_info = json.loads(response.text)
                hostname = assets_data[assets_id]
                sys_users_priority = sys_auth_info['priority']
                if hostname not in data['_meta']['hostvars']:
                    data['_meta']['hostvars'][hostname] = dict()

                if 'priority' not in temp_hostvars[hostname] or \
                        sys_users_priority > temp_hostvars[hostname]['priority']:

                    temp_hostvars[hostname]['priority'] = sys_users_priority
                    data['_meta']['hostvars'][hostname].clear()
                    data['_meta']['hostvars'][hostname]['ansible_user'] = sys_auth_info['username']
                    data['_meta']['hostvars'][hostname]['ansible_password'] = sys_auth_info['password']
                    data['_meta']['hostvars'][hostname]['ansible_host'] = temp_hostvars[hostname]['ansible_host']
                    data['_meta']['hostvars'][hostname]['ansible_port'] = temp_hostvars[hostname]['ansible_port']

                    if sys_auth_info['protocol'] == "rdp":
                        data['_meta']['hostvars'][hostname]['ansible_connection'] = "winrm"
                        data['_meta']['hostvars'][hostname]['ansible_port'] = 5985
                        data['_meta']['hostvars'][hostname]['ansible_winrm_transport'] = "ntlm"
                        data['_meta']['hostvars'][hostname]['ansible_winrm_server_cert_validation'] = "ignore"

        return data

    def __init__(self):
        self.jms_server = None
        self.jms_username = None
        self.jms_password = None
        # 通过文件获取认证信息
        # self.read_settings()
        self.options = self.read_cli()
        # 通过awx-crendential的env获取认证信息
        self.jms_server = os.environ.get('JMS_SERVER')
        self.jms_username = os.environ.get('JMS_USERNAME')
        self.jms_password = os.environ.get('JMS_PASSWORD')

        if self.jms_server and self.jms_username:
            try:
                url_auth = URL_AUTH % self.jms_server
                query_args = {
                    "username": self.jms_username,
                    "password": self.jms_password
                }
                response = requests.post(url_auth, data=query_args)
                token = json.loads(response.text)['token']
            except (Exception, SystemExit):
                sys.stderr.write("Error: Could not login to Jumpserver. Check your jms.yml.\n")
                sys.exit(1)

            # if self.options.host:
            #     data = self.get_host(token, self.options.host)
            #     print(json.dumps(data, indent=2))

            if self.options.list:
                data = self.get_list(token)
                print(json.dumps(data, indent=2))

            else:
                sys.stderr.write("usage: --list  ..OR.. --host <hostname>\n")
                sys.exit(1)

        else:
            sys.stderr.write("Error: Configuration of server and credentials are required. Please Check credential.\n")
            sys.exit(1)


JumpserverInventory()
