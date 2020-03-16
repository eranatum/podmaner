import yaml
import subprocess
import re
import json
import glob
import os
import sys


class Podmaner():
    """Class to deal with podman containers"""
    def __init__(self, container_name, config_path='/etc/podmaner.d/'):
        self.container_name = container_name
        self.config_path = config_path
        self.config = {}
        self.cnt_info = {}

    def read_config_file(self):
        conf_file = self.config_path + self.container_name + '.yaml'
        self.__check_conf_exists(conf_file)
        with open(conf_file, 'r') as config:
            self.config = yaml.load(config, yaml.FullLoader)

    def __check_conf_exists(self, conf_file_name):
        try:
            with open(conf_file_name, 'r'):
                pass
        except FileNotFoundError:
            print("Config file not found - creating default one")
            self.__init_config(conf_file_name)

    def __init_config(self, conf_file_name):
        config_dict = {'podman_exec_path': '/usr/bin/podman',
                       'container_dns_name': self.container_name + '.d.om',
                       'cni_lib_paths':
                       ['/var/lib/cni/networks/podman/',
                        '/var/lib/cni/results/']}
        with open(conf_file_name, 'w') as config_dest:
            yaml.dump(config_dict, config_dest)

    def print_help(self):
        pass

    def __check_cni_error(self, app_output_err):
        cni_error_re = r'(.*)(Error adding network: failed to allocate for range 0: requested IP address)(.*)'
        cni_error_string = re.compile(cni_error_re)
        if re.match(cni_error_string, app_output_err):
            self.__cleanup_cni()

    def __cleanup_cni(self):
        to_del_cni = self.__pick_cni_files()
        for del_file in to_del_cni:
            print("Self heal: Deleting file - " + del_file)
            os.remove(del_file)

    def __pick_cni_files(self):
        cni_files = []
        cni_ip_addr = ''
        for cni_dirs in self.config['cni_lib_paths']:
            cni_re = cni_dirs + '*' + self.cnt_info[0]['Id'] + '*'
            cni_files += glob.glob(cni_re)

        wanted_eth_re = r'(.*)(podman-)(' + (self.cnt_info[0]['Id']) + ')(-eth.*)'
        wanted_eth_string = re.compile(wanted_eth_re)

        for cni_file in cni_files:
            if re.match(wanted_eth_string, cni_file):
                with open(cni_file, 'r') as cni_file_fp:
                    cni_json = json.load(cni_file_fp)
                    ip_string_re = r'(\d+\.\d+\.\d+\.\d+)/(\d+)'
                    ip_string = re.compile(ip_string_re)
                    if re.match(ip_string, cni_json['ips'][0]['address']):
                        ip_search = re.search(ip_string, cni_json['ips'][0]['address'])
                        cni_ip_addr = ip_search.group(1)
                    else:
                        print("Cannot find container ip address in: "
                              + str(cni_file))

        for cni_dirs in self.config['cni_lib_paths']:
            cni_re = cni_dirs + cni_ip_addr
            cni_files += glob.glob(cni_re)

        return cni_files

    def __cnt_start(self):
        cnt_process = subprocess.Popen([self.config['podman_exec_path'],
                                       'start', self.container_name],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        out, err = cnt_process.communicate()
        return out, err, cnt_process.returncode

    def __get_cnt_info(self):
        cnt_process = subprocess.Popen([self.config['podman_exec_path'],
                                       'inspect', self.container_name],
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        out, err = cnt_process.communicate()
        self.cnt_info = json.loads(out)

    def start_container(self):
        start_counter = 0
        while start_counter <= 10:
            out, err, cnt_ec = self.__cnt_start()
            if cnt_ec == 0:
                print("Container " + self.container_name + " started successfuly!")
                sys.exit(0)
            self.__get_cnt_info()
            self.__check_cni_error(str(err))
            ++start_counter
