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
        self.lock_file = '/var/lock/' + self.container_name + '_podman.lock'

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

    def __podman_exec(self, command):
        podman_command_args = {'start': ['start', self.container_name],
                               'stop': ['stop', '-t', '10', self.container_name],
                               'ps': ['ps', '-a', '--format', 'json', '--filter', "name="+self.container_name],
                               'inspect': ['inspect', self.container_name]}
        proc_args = [self.config['podman_exec_path']] + podman_command_args[command]
        podman_proc = subprocess.Popen(proc_args,
                                       stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE)
        podman_proc.args
        out, err = podman_proc.communicate()

        return out, err, podman_proc.returncode

    def __cnt_start(self):
        return self.__podman_exec('start')

    def __get_cnt_info(self):
        out, err, cnt_ec = self.__podman_exec('inspect')
        self.cnt_info = json.loads(out)

    def start_container(self):
        start_counter = 0
        self.__lock()
        while start_counter <= 10:
            out, err, cnt_ec = self.__cnt_start()
            if cnt_ec == 0:
                print("Container " + self.container_name + " started successfuly!")
                self.__lock()
                sys.exit(0)
            self.__check_cni_error(str(err))
            ++start_counter

    def stop_container(self):
        out, err, ret_code = self.__podman_exec('stop')
        self.__lock()

    def __cnt_alive(self):
        # in this case if command succeds the out variable will be JSON
        out, err, cnt_ec = self.__podman_exec('ps')
        cnt_health = json.loads(out)
        up_status_re = r'(^Up)(.*)'
        up_status = re.compile(up_status_re)

        if re.match(up_status, cnt_health[0]['Status']):
            return True
        else:
            return False

    def __check_lock_exists(self):
        if os.path.exists(self.lock_file):
            return True
        else:
            return False

    def __lock(self):
        lock_status = self.__check_lock_exists()
        cnt_status = self.__cnt_alive()
        self.__get_cnt_info()
        cnt_pid_file = '/var/run/containers/storage/overlay-containers/'
        + self.cnt_info[0]['Id'] + '/userdata/pidfile'
        if lock_status and cnt_status:
            print("Lock file " + self.lock_file + " exists"
                  + " and container is running - exiting")
            sys.exit(0)
        if lock_status is False and cnt_status:
            print("Container is running but somehow there is no lock file - creating one")
            with open(self.lock_file, 'w') as lock:
                lock.write(str(self.container_name))

            os.symlink(cnt_pid_file, '/var/run/' + self.config_path + '_podman.pid')

        if lock_status and cnt_status is False:
            print("Lock file exists but container is not running - removing lockfile")
            os.remove(self.lock_file)
            os.remove(cnt_pid_file)
