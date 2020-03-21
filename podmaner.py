import yaml
import subprocess
import re
import json
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
        self._check_conf_exists(conf_file)
        with open(conf_file, 'r') as config:
            self.config = yaml.load(config, yaml.FullLoader)

    def _check_conf_exists(self, conf_file_name):
        try:
            with open(conf_file_name, 'r'):
                pass
        except FileNotFoundError:
            print("Config file not found - creating default one")
            self._init_config(conf_file_name)

    def _init_config(self, conf_file_name):
        config_dict = {'podman_exec_path': '/usr/bin/podman',
                       'container_dns_name': self.container_name + '.d.om',
                       'cni_lib_paths':
                       ['/var/lib/cni/networks/podman/',
                        '/var/lib/cni/results/']}
        with open(conf_file_name, 'w') as config_dest:
            yaml.dump(config_dict, config_dest)

    def _check_cni_error(self, app_output_err):
        cni_error_re = r'(.*)(Error adding network: failed to allocate for range 0: requested IP address)(.*)'
        cni_error_string = re.compile(cni_error_re)
        if re.match(cni_error_string, app_output_err):
            self._cleanup_cni()

    def _cleanup_cni(self):
        self._get_cnt_info()
        to_del_cni = self._pick_cni_files()
        for del_file in to_del_cni:
            print("Self heal: Deleting file - " + del_file)
            try:
                os.remove(del_file)
            except IsADirectoryError:
                print(del_file + " is a directory - will not remove it")

    def _pick_cni_files(self):
        ip_re = r'(\d+\.\d+\.\d+\.\d+)'
        cnt_id = self.cnt_info[0]['Id']
        cnt_f_re = rf'(.*)(podman-)({cnt_id})(-eth.*)'
        files_to_del = []
        ip_cmp = re.compile(ip_re)
        id_re = r'.*(' + self.cnt_info[0]['Id'] + ')(.*)'
        id_cmp = re.compile(id_re)
        cnt_f_cmp = re.compile(cnt_f_re)
        for cni_dir in self.config['cni_lib_paths']:
            dir_files = os.listdir(cni_dir)
            for file in dir_files:
                if re.match(cnt_f_cmp, file):
                    files_to_del.append(cni_dir + file)
                if re.match(ip_cmp, file):
                    with open(cni_dir + file, 'r') as ip_file:
                        if re.match(id_cmp, ip_file.readline()):
                            files_to_del.append(cni_dir + file)
        return files_to_del

    def _podman_exec(self, command):
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

    def _cnt_start(self):
        return self._podman_exec('start')

    def _get_cnt_info(self):
        out, err, cnt_ec = self._podman_exec('inspect')
        self.cnt_info = json.loads(out)

    def start_container(self):
        start_counter = 0
        self._lock()
        while start_counter <= 10:
            out, err, cnt_ec = self._cnt_start()
            if cnt_ec == 0:
                print("Container " + self.container_name + " started successfuly!")
                self._lock()
                sys.exit(0)
            self._check_cni_error(str(err))
            start_counter += 1

    def stop_container(self):
        out, err, ret_code = self._podman_exec('stop')
        self._lock()

    def _cnt_alive(self):
        # in this case if command succeds the out variable will be JSON
        out, err, cnt_ec = self._podman_exec('ps')
        cnt_health = json.loads(out)
        up_status_re = r'(^Up)(.*)'
        up_status = re.compile(up_status_re)

        if re.match(up_status, cnt_health[0]['Status']):
            return True
        else:
            return False

    def _check_lock_exists(self):
        if os.path.exists(self.lock_file):
            return True
        else:
            return False

    def _lock(self):
        lock_status = self._check_lock_exists()
        cnt_status = self._cnt_alive()
        self._get_cnt_info()
        cnt_ovrlay_path = '/var/run/containers/storage/overlay-containers/'
        cnt_pid_file = cnt_ovrlay_path + self.cnt_info[0]['Id'] + '/userdata/pidfile'
        if lock_status and cnt_status:
            print("Lock file " + self.lock_file + " exists"
                  + " and container is running - exiting")
            sys.exit(0)
        if lock_status is False and cnt_status:
            print("Container is running but somehow there is no lock file - creating one")
            with open(self.lock_file, 'w') as lock:
                lock.write(str(self.container_name))

            os.symlink(cnt_pid_file, '/var/run/' + self.container_name + '_podman.pid')

        if lock_status and cnt_status is False:
            print("Lock file exists but container is not running - removing lockfile")
            os.remove(self.lock_file)
            os.remove('/var/run/' + self.container_name + '_podman.pid')
