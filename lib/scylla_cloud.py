#!/usr/bin/env python3
#
# Copyright 2022 ScyllaDB
#
# SPDX-License-Identifier: Apache-2.0

import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import psutil
import socket
import glob
import distro
import base64
import datetime
from subprocess import run, CalledProcessError
from abc import ABCMeta, abstractmethod


def out(cmd, shell=True, timeout=None, encoding='utf-8', ignore_error=False, user=None, group=None):
    try:
        res = run(cmd, capture_output=True, shell=shell, timeout=timeout, check=not ignore_error, encoding=encoding, user=user, group=group)
    except CalledProcessError as e:
        print(f'''
Command '{cmd}' returned non-zero exit status: {e.returncode}
----------  stdout  ----------
{e.stdout.strip()}
------------------------------
----------  stderr  ----------
{e.stderr.strip()}
------------------------------
'''[1:-1])
        raise
    return res.stdout.strip()


import sys
import traceback
import traceback_with_variables
import logging


def scylla_excepthook(etype, value, tb):
    os.makedirs('/var/tmp/scylla', mode=0o755, exist_ok=True)
    traceback.print_exception(etype, value, tb)
    exc_logger = logging.getLogger(__name__)
    exc_logger.setLevel(logging.DEBUG)
    exc_logger_file = f'/var/tmp/scylla/{os.path.basename(sys.argv[0])}-{os.getpid()}-debug.log'
    exc_logger.addHandler(logging.FileHandler(exc_logger_file))
    traceback_with_variables.print_exc(e=value, file_=traceback_with_variables.LoggerAsFile(exc_logger))
    print(f'Debug log created: {exc_logger_file}')

sys.excepthook = scylla_excepthook


# @param headers dict of k:v
def curl(url, headers=None, method=None, byte=False, timeout=3, max_retries=5, retry_interval=5):
    retries = 0
    while True:
        try:
            req = urllib.request.Request(url, headers=headers or {}, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as res:
                if byte:
                    return res.read()
                else:
                    return res.read().decode('utf-8')
        except (urllib.error.URLError, socket.timeout):
            time.sleep(retry_interval)
            retries += 1
            if retries >= max_retries:
                raise


class cloud_instance(metaclass=ABCMeta):
    @abstractmethod
    def get_local_disks(self):
        pass

    @abstractmethod
    def get_remote_disks(self):
        pass

    @abstractmethod
    def private_ipv4(self):
        pass

    @abstractmethod
    def is_supported_instance_class(self):
        pass

    @property
    @abstractmethod
    def instancetype(self):
        pass

    @abstractmethod
    def io_setup(self):
        pass

    @staticmethod
    @abstractmethod
    def check():
        pass

    @property
    @abstractmethod
    def user_data(self):
        pass

    @property
    @abstractmethod
    def nvme_disk_count(self):
        pass

    @property
    @abstractmethod
    def endpoint_snitch(self):
        pass

    @property
    @abstractmethod
    def getting_started_url(self):
        pass


class gcp_instance(cloud_instance):
    """Describe several aspects of the current GCP instance"""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"
    ROOT = "root"
    GETTING_STARTED_URL = "http://www.scylladb.com/doc/getting-started-google/"
    META_DATA_BASE_URL = "http://metadata.google.internal/computeMetadata/v1/instance/"
    ENDPOINT_SNITCH = "GoogleCloudSnitch"

    def __init__(self):
        self.__type = None
        self.__cpu = None
        self.__memoryGB = None
        self.__nvmeDiskCount = None
        self.__firstNvmeSize = None
        self.__osDisks = None

    @property
    def endpoint_snitch(self):
        return self.ENDPOINT_SNITCH

    @property
    def getting_started_url(self):
        return self.GETTING_STARTED_URL

    @staticmethod
    def is_gce_instance():
        """Check if it's GCE instance via DNS lookup to metadata server."""
        try:
            addrlist = socket.getaddrinfo('metadata.google.internal', 80)
        except socket.gaierror:
            return False
        for res in addrlist:
            af, socktype, proto, canonname, sa = res
            if af == socket.AF_INET:
                addr, port = sa
                if addr == "169.254.169.254":
                    # Make sure it is not on GKE
                    try:
                        gcp_instance().__instance_metadata("machine-type")
                    except urllib.error.HTTPError:
                        return False
                    return True
        return False

    def __instance_metadata(self, path, recursive=False):
        return curl(self.META_DATA_BASE_URL + path + "?recursive=%s" % str(recursive).lower(),
                    headers={"Metadata-Flavor": "Google"})

    def is_in_root_devs(self, x, root_devs):
        for root_dev in root_devs:
            if root_dev.startswith(os.path.join("/dev/", x)):
                return True
        return False

    def _non_root_nvmes(self):
        """get list of nvme disks from os, filter away if one of them is root"""
        nvme_re = re.compile(r"nvme\d+n\d+$")

        root_dev_candidates = [x for x in psutil.disk_partitions() if x.mountpoint == "/"]

        root_devs = [x.device for x in root_dev_candidates]

        nvmes_present = list(filter(nvme_re.match, os.listdir("/dev")))
        return {self.ROOT: root_devs, self.EPHEMERAL: [x for x in nvmes_present if not self.is_in_root_devs(x, root_devs)]}

    def _non_root_disks(self):
        """get list of disks from os, filter away if one of them is root"""
        disk_re = re.compile(r"/dev/sd[b-z]+$")

        root_dev_candidates = [x for x in psutil.disk_partitions() if x.mountpoint == "/"]

        root_devs = [x.device for x in root_dev_candidates]

        disks_present = list(filter(disk_re.match, glob.glob("/dev/sd*")))
        return {self.PERSISTENT: [x.lstrip('/dev/') for x in disks_present if not self.is_in_root_devs(x.lstrip('/dev/'), root_devs)]}

    @property
    def os_disks(self):
        """populate disks from /dev/ and root mountpoint"""
        if self.__osDisks is None:
            __osDisks = {}
            nvmes_present = self._non_root_nvmes()
            for k, v in nvmes_present.items():
                __osDisks[k] = v
            disks_present = self._non_root_disks()
            for k, v in disks_present.items():
                __osDisks[k] = v
            self.__osDisks = __osDisks
        return self.__osDisks

    def get_local_disks(self):
        """return just transient disks"""
        return self.os_disks[self.EPHEMERAL]

    def get_remote_disks(self):
        """return just persistent disks"""
        return self.os_disks[self.PERSISTENT]

    @staticmethod
    def isNVME(gcpdiskobj):
        """check if disk from GCP metadata is a NVME disk"""
        if gcpdiskobj["interface"]=="NVME":
            return True
        return False

    def __get_nvme_disks_from_metadata(self):
        """get list of nvme disks from metadata server"""
        try:
            disksREST=self.__instance_metadata("disks", True)
            disksobj=json.loads(disksREST)
            nvmedisks=list(filter(self.isNVME, disksobj))
        except Exception as e:
            print ("Problem when parsing disks from metadata:")
            print (e)
            nvmedisks={}
        return nvmedisks

    @property
    def nvme_disk_count(self):
        """get # of nvme disks available for scylla raid"""
        if self.__nvmeDiskCount is None:
            try:
                ephemeral_disks = self.get_local_disks()
                count_os_disks=len(ephemeral_disks)
            except Exception as e:
                print ("Problem when parsing disks from OS:")
                print (e)
                count_os_disks=0
            nvme_metadata_disks = self.__get_nvme_disks_from_metadata()
            count_metadata_nvme_disks=len(nvme_metadata_disks)
            self.__nvmeDiskCount = count_os_disks if count_os_disks<count_metadata_nvme_disks else count_metadata_nvme_disks
        return self.__nvmeDiskCount

    @property
    def instancetype(self):
        """return the type of this instance, e.g. n2-standard-2"""
        if self.__type is None:
            self.__type = self.__instance_metadata("machine-type").split("/")[-1]
        return self.__type

    @property
    def cpu(self):
        """return the # of cpus of this instance"""
        if self.__cpu is None:
            self.__cpu = psutil.cpu_count()
        return self.__cpu

    @property
    def memoryGB(self):
        """return the size of memory in GB of this instance"""
        if self.__memoryGB is None:
            self.__memoryGB = psutil.virtual_memory().total/1024/1024/1024
        return self.__memoryGB

    def instance_size(self):
        """Returns the size of the instance we are running in. i.e.: 2"""
        instancetypesplit = self.instancetype.split("-")
        return instancetypesplit[2] if len(instancetypesplit)>2 else 0

    def instance_class(self):
        """Returns the class of the instance we are running in. i.e.: n2"""
        return self.instancetype.split("-")[0]

    def instance_purpose(self):
        """Returns the purpose of the instance we are running in. i.e.: standard"""
        return self.instancetype.split("-")[1]

    m1supported="m1-megamem-96" #this is the only exception of supported m1 as per https://cloud.google.com/compute/docs/machine-types#m1_machine_types

    def is_unsupported_instance_class(self):
        """Returns if this instance type belongs to unsupported ones for nvmes"""
        if self.instancetype == self.m1supported:
            return False
        if self.instance_class() in ['e2', 'f1', 'g1', 'm2', 'm1']:
            return True
        return False

    def is_supported_instance_class(self):
        """Returns if this instance type belongs to supported ones for nvmes"""
        if self.instancetype == self.m1supported:
            return True
        if self.instance_class() in ['n1', 'n2', 'n2d' ,'c2']:
            return True
        return False

    def is_recommended_instance_size(self):
        """if this instance has at least 2 cpus, it has a recommended size"""
        if int(self.instance_size()) > 1:
            return True
        return False

    def zone(self):
        """Returns zone. i.e.: us-east1-b"""
        return self.__instance_metadata("zone").rsplit('/', 1)[1]

    @staticmethod
    def get_file_size_by_seek(filename):
        "Get the file size by seeking at end"
        fd= os.open(filename, os.O_RDONLY)
        try:
            return os.lseek(fd, 0, os.SEEK_END)
        finally:
            os.close(fd)

    # note that GCP has 3TB physical devices actually, which they break into smaller 375GB disks and share the same mem with multiple machines
    # this is a reference value, disk size shouldn't be lower than that
    GCP_NVME_DISK_SIZE_2020=375

    @property
    def firstNvmeSize(self):
        """return the size of first non root NVME disk in GB"""
        if self.__firstNvmeSize is None:
            ephemeral_disks = self.get_local_disks()
            if len(ephemeral_disks) > 0:
                firstDisk = ephemeral_disks[0]
                firstDiskSize = self.get_file_size_by_seek(os.path.join("/dev/", firstDisk))
                firstDiskSizeGB = firstDiskSize/1024/1024/1024
                if firstDiskSizeGB >= self.GCP_NVME_DISK_SIZE_2020:
                    self.__firstNvmeSize = firstDiskSizeGB
                else:
                    self.__firstNvmeSize = 0
                    logging.warning("First nvme is smaller than lowest expected size. ".format(firstDisk))
            else:
                self.__firstNvmeSize = 0
        return self.__firstNvmeSize

    def is_recommended_instance(self):
        if not self.is_unsupported_instance_class() and self.is_supported_instance_class() and self.is_recommended_instance_size():
            # at least 1:2GB cpu:ram ratio , GCP is at 1:4, so this should be fine
            if self.cpu/self.memoryGB < 0.5:
                diskCount = self.nvme_disk_count
                # to reach max performance for > 16 disks we mandate 32 or more vcpus
                # https://cloud.google.com/compute/docs/disks/local-ssd#performance
                if diskCount >= 16 and self.cpu < 32:
                    logging.warning(
                        "This machine doesn't have enough CPUs for allocated number of NVMEs (at least 32 cpus for >=16 disks). Performance will suffer.")
                if diskCount < 1:
                    logging.warning("No ephemeral disks were found.")
                    return False
                diskSize = self.firstNvmeSize
                max_disktoramratio = 105
                # 30:1 Disk/RAM ratio must be kept at least(AWS), we relax this a little bit
                # on GCP we are OK with {max_disktoramratio}:1 , n1-standard-2 can cope with 1 disk, not more
                disktoramratio = (diskCount * diskSize) / self.memoryGB
                if (disktoramratio > max_disktoramratio):
                    logging.warning(
                        f"Instance disk-to-RAM ratio is {disktoramratio}, which is higher than the recommended ratio {max_disktoramratio}. Performance may suffer.")
                    return False
                return True
            else:
                logging.warning("At least 2G of RAM per CPU is needed. Performance will suffer.")
        return False

    def private_ipv4(self):
        return self.__instance_metadata("network-interfaces/0/ip")

    @staticmethod
    def check():
        pass

    def io_setup(self):
        run('/opt/scylladb/scylla-machine-image/scylla_cloud_io_setup', check=True, shell=True)

    @property
    def user_data(self):
        try:
            return self.__instance_metadata("attributes/user-data")
        except urllib.error.HTTPError:  # empty user-data
            return ""


class azure_instance(cloud_instance):
    """Describe several aspects of the current Azure instance"""

    EPHEMERAL = "ephemeral"
    PERSISTENT = "persistent"
    SWAP = "swap"
    ROOT = "root"
    GETTING_STARTED_URL = "http://www.scylladb.com/doc/getting-started-azure/"
    ENDPOINT_SNITCH = "AzureSnitch"
    META_DATA_BASE_URL = "http://169.254.169.254/metadata/instance"

    def __init__(self):
        self.__type = None
        self.__cpu = None
        self.__location = None
        self.__zone = None
        self.__memoryGB = None
        self.__nvmeDiskCount = None
        self.__firstNvmeSize = None
        self.__osDisks = None

    @property
    def endpoint_snitch(self):
        return self.ENDPOINT_SNITCH

    @property
    def getting_started_url(self):
        return self.GETTING_STARTED_URL

    @classmethod
    def is_azure_instance(cls):
        """Check if it's Azure instance via query to metadata server."""
        try:
            curl(cls.META_DATA_BASE_URL + cls.API_VERSION + "&format=text", headers = { "Metadata": "True" }, max_retries=2, retry_interval=1)
            return True
        except (urllib.error.URLError, urllib.error.HTTPError):
            return False

# as per https://docs.microsoft.com/en-us/azure/virtual-machines/windows/instance-metadata-service?tabs=windows#supported-api-versions
    API_VERSION = "?api-version=2021-01-01"

    def __instance_metadata(self, path):
        """query Azure metadata server"""
        return curl(self.META_DATA_BASE_URL + path + self.API_VERSION + "&format=text", headers = { "Metadata": "True" })

    def is_in_root_devs(self, x, root_devs):
        for root_dev in root_devs:
            if root_dev.startswith(os.path.join("/dev/", x)):
                return True
        return False

    def _non_root_nvmes(self):
        """get list of nvme disks from os, filter away if one of them is root"""
        nvme_re = re.compile(r"nvme\d+n\d+$")

        root_dev_candidates = [x for x in psutil.disk_partitions() if x.mountpoint == "/"]
        if len(root_dev_candidates) != 1:
            raise Exception("found more than one disk mounted at root ".format(root_dev_candidates))

        root_devs = [x.device for x in root_dev_candidates]

        nvmes_present = list(filter(nvme_re.match, os.listdir("/dev")))
        return {self.ROOT: root_devs, self.EPHEMERAL: [x for x in nvmes_present if not self.is_in_root_devs(x, root_devs)]}

    def _get_swap_dev(self):
        if os.path.exists('/dev/disk/cloud/azure_resource'):
            return os.path.realpath('/dev/disk/cloud/azure_resource')
        else:
            return None

    def _non_root_disks(self):
        """get list of disks from os, filter away if one of them is root"""
        disk_re = re.compile(r"/dev/sd[b-z]+$")

        root_dev_candidates = [x for x in psutil.disk_partitions() if x.mountpoint == "/"]

        root_devs = [x.device for x in root_dev_candidates]

        disks_present = list(filter(disk_re.match, glob.glob("/dev/sd*")))
        swap_dev = self._get_swap_dev()
        swap = []
        if swap_dev:
            swap.append(swap_dev.lstrip('/dev/'))
        persistent = [x.lstrip('/dev/') for x in disks_present if not self.is_in_root_devs(x.lstrip('/dev/'), root_devs) and not x == swap_dev]
        return {self.PERSISTENT: persistent, self.SWAP: swap}

    @property
    def os_disks(self):
        """populate disks from /dev/ and root mountpoint"""
        if self.__osDisks is None:
            __osDisks = {}
            nvmes_present = self._non_root_nvmes()
            for k, v in nvmes_present.items():
                __osDisks[k] = v
            disks_present = self._non_root_disks()
            for k, v in disks_present.items():
                __osDisks[k] = v
            self.__osDisks = __osDisks
        return self.__osDisks

    def get_local_disks(self):
        """return just transient disks"""
        return self.os_disks[self.EPHEMERAL]

    def get_remote_disks(self):
        """return just persistent disks"""
        return self.os_disks[self.PERSISTENT]

    def get_swap_disks(self):
        return self.os_disks[self.SWAP]

    @property
    def nvme_disk_count(self):
        """get # of nvme disks available for scylla raid"""
        if self.__nvmeDiskCount is None:
            try:
                ephemeral_disks = self.get_local_disks()
                count_os_disks = len(ephemeral_disks)
            except Exception as e:
                print("Problem when parsing disks from OS:")
                print(e)
                count_os_disks = 0
            count_metadata_nvme_disks = self.__get_nvme_disks_count_from_metadata()
            self.__nvmeDiskCount = count_os_disks if count_os_disks < count_metadata_nvme_disks else count_metadata_nvme_disks
        return self.__nvmeDiskCount

    instanceToDiskCount = {
        "L8s": 1,
        "L16s": 2,
        "L32s": 4,
        "L48s": 6,
        "L64s": 8,
        "L80s": 10,
        "L8as": 1,
        "L16as": 2,
        "L32as": 4,
        "L48as": 6,
        "L64as": 8,
        "L80as": 10
    }

    def __get_nvme_disks_count_from_metadata(self):
        #storageProfile in VM metadata lacks the number of NVMEs, it's hardcoded based on VM type
        return self.instanceToDiskCount.get(self.instance_class(), 0)

    @property
    def instancelocation(self):
        """return the location of this instance, e.g. eastus"""
        if self.__location is None:
            self.__location = self.__instance_metadata("/compute/location")
        return self.__location

    @property
    def instancezone(self):
        """return the zone of this instance, e.g. 1"""
        if self.__zone is None:
            self.__zone = self.__instance_metadata("/compute/zone")
        return self.__zone

    @property
    def instancetype(self):
        """return the type of this instance, e.g. Standard_L8s_v2"""
        if self.__type is None:
            self.__type = self.__instance_metadata("/compute/vmSize")
        return self.__type

    @property
    def cpu(self):
        """return the # of cpus of this instance"""
        if self.__cpu is None:
            self.__cpu = psutil.cpu_count()
        return self.__cpu

    @property
    def memoryGB(self):
        """return the size of memory in GB of this instance"""
        if self.__memoryGB is None:
            self.__memoryGB = psutil.virtual_memory().total/1024/1024/1024
        return self.__memoryGB

    def instance_purpose(self):
        """Returns the class of the instance we are running in. i.e.: Standard"""
        return self.instancetype.split("_")[0]

    def instance_class(self):
        """Returns the purpose of the instance we are running in. i.e.: L8s"""
        return self.instancetype.split("_")[1]

    def is_supported_instance_class(self):
        """Returns if this instance type belongs to supported ones for nvmes"""
        if self.instance_class() in list(self.instanceToDiskCount.keys()):
            return True
        return False

    def is_recommended_instance_size(self):
        """if this instance has at least 2 cpus, it has a recommended size"""
        if self.cpu > 1:
            return True
        return False

    def is_recommended_instance(self):
        if self.is_supported_instance_class():
            return True
        return False

    def private_ipv4(self):
        return self.__instance_metadata("/network/interface/0/ipv4/ipAddress/0/privateIpAddress")

    @staticmethod
    def check():
        pass

    def io_setup(self):
        run('/opt/scylladb/scylla-machine-image/scylla_cloud_io_setup', check=True, shell=True)

    @property
    def user_data(self):
        encoded_user_data = self.__instance_metadata("/compute/userData")
        if not encoded_user_data:
            return ''
        return base64.b64decode(encoded_user_data).decode()


class aws_instance(cloud_instance):
    """Describe several aspects of the current AWS instance"""
    GETTING_STARTED_URL = "http://www.scylladb.com/doc/getting-started-amazon/"
    META_DATA_BASE_URL = "http://169.254.169.254/latest/"
    ENDPOINT_SNITCH = "Ec2Snitch"
    METADATA_TOKEN_TTL = 21600

    def __disk_name(self, dev):
        name = re.compile(r"(?:/dev/)?(?P<devname>[a-zA-Z]+)\d*")
        return name.search(dev).group("devname")

    def __refresh_metadata_token(self):
        self._metadata_token_time = datetime.datetime.now()
        self._metadata_token = curl(self.META_DATA_BASE_URL + "api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": self.METADATA_TOKEN_TTL}, method="PUT")

    def __instance_metadata(self, path):
        if not self._metadata_token:
            self.__refresh_metadata_token()
        else:
            time_diff = datetime.datetime.now() - self._metadata_token_time
            time_diff_sec = int(time_diff.total_seconds())
            if time_diff_sec >= self.METADATA_TOKEN_TTL - 120:
                self.__refresh_metadata_token()
        return curl(self.META_DATA_BASE_URL + "meta-data/" + path, headers={"X-aws-ec2-metadata-token": self._metadata_token})

    def __device_exists(self, dev):
        if dev[0:4] != "/dev":
            dev = "/dev/%s" % dev
        return os.path.exists(dev)

    def __xenify(self, devname):
        dev = self.__instance_metadata('block-device-mapping/' + devname)
        return dev.replace("sd", "xvd")

    def __filter_nvmes(self, dev, dev_type):
        nvme_re = re.compile(r"(nvme\d+)n\d+$")
        match = nvme_re.match(dev)
        if not match:
            return False
        nvme_name = match.group(1)
        with open(f'/sys/class/nvme/{nvme_name}/model') as f:
            model = f.read().strip()
        if dev_type == 'ephemeral':
            return model != 'Amazon Elastic Block Store'
        else:
            return model == 'Amazon Elastic Block Store'

    def _non_root_nvmes(self):
        nvme_re = re.compile(r"nvme\d+n\d+$")

        root_dev_candidates = [ x for x in psutil.disk_partitions() if x.mountpoint == "/" ]
        if len(root_dev_candidates) != 1:
            raise Exception("found more than one disk mounted at root'".format(root_dev_candidates))

        root_dev = root_dev_candidates[0].device
        if root_dev == '/dev/root':
            root_dev = out('findmnt -n -o SOURCE /')
        ephemeral_present = list(filter(lambda x: self.__filter_nvmes(x, 'ephemeral'), os.listdir("/dev")))
        ebs_present = list(filter(lambda x: self.__filter_nvmes(x, 'ebs'), os.listdir("/dev")))
        return {"root": [ root_dev ], "ephemeral": ephemeral_present, "ebs": [ x for x in ebs_present if not root_dev.startswith(os.path.join("/dev/", x))] }

    def __populate_disks(self):
        devmap = self.__instance_metadata("block-device-mapping")
        self._disks = {}
        devname = re.compile("^\D+")
        nvmes_present = self._non_root_nvmes()
        for k,v in nvmes_present.items():
            self._disks[k] = v

        for dev in devmap.splitlines():
            t = devname.match(dev).group()
            if t == "ephemeral" and nvmes_present:
                continue
            if t not in self._disks:
                self._disks[t] = []
            if not self.__device_exists(self.__xenify(dev)):
                continue
            self._disks[t] += [self.__xenify(dev)]
        if not 'ebs' in self._disks:
            self._disks['ebs'] = []

    def __mac_address(self, nic='eth0'):
        with open('/sys/class/net/{}/address'.format(nic)) as f:
            return f.read().strip()

    def __init__(self):
        self._metadata_token = None
        self._metadata_token_time = None
        self._type = self.__instance_metadata("instance-type")
        self.__populate_disks()

    @property
    def endpoint_snitch(self):
        return self.ENDPOINT_SNITCH

    @property
    def getting_started_url(self):
        return self.GETTING_STARTED_URL

    @classmethod
    def is_aws_instance(cls):
        """Check if it's AWS instance via query to metadata server."""
        try:
            curl(cls.META_DATA_BASE_URL + "api/token", headers={"X-aws-ec2-metadata-token-ttl-seconds": cls.METADATA_TOKEN_TTL}, method="PUT")
            return True
        except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout):
            return False

    @property
    def instancetype(self):
        """Returns which instance we are running in. i.e.: i3.16xlarge"""
        return self._type

    def instance_size(self):
        """Returns the size of the instance we are running in. i.e.: 16xlarge"""
        return self._type.split(".")[1]

    def instance_class(self):
        """Returns the class of the instance we are running in. i.e.: i3"""
        return self._type.split(".")[0]

    def is_supported_instance_class(self):
        if self.instance_class() in ['i2', 'i3', 'i3en', 'c5d', 'm5d', 'm5ad', 'r5d', 'z1d', 'c6gd', 'm6gd', 'r6gd', 'x2gd', 'im4gn', 'is4gen', 'i4i']:
            return True
        return False

    def get_en_interface_type(self):
        instance_class = self.instance_class()
        instance_size = self.instance_size()
        if instance_class in ['c3', 'c4', 'd2', 'i2', 'r3']:
            return 'ixgbevf'
        if instance_class in ['a1', 'c5', 'c5a', 'c5d', 'c5n', 'c6g', 'c6gd', 'f1', 'g3', 'g4', 'h1', 'i3', 'i3en', 'inf1', 'm5', 'm5a', 'm5ad', 'm5d', 'm5dn', 'm5n', 'm6g', 'm6gd', 'p2', 'p3', 'r4', 'r5', 'r5a', 'r5ad', 'r5b', 'r5d', 'r5dn', 'r5n', 't3', 't3a', 'u-6tb1', 'u-9tb1', 'u-12tb1', 'u-18tn1', 'u-24tb1', 'x1', 'x1e', 'z1d', 'c6g', 'c6gd', 'm6g', 'm6gd', 't4g', 'r6g', 'r6gd', 'x2gd', 'im4gn', 'is4gen', 'i4i']:
            return 'ena'
        if instance_class == 'm4':
            if instance_size == '16xlarge':
                return 'ena'
            else:
                return 'ixgbevf'
        return None

    def availability_zone(self):
        """Returns availability zone. i.e.: us-east-1b"""
        return self.__instance_metadata("placement/availability-zone")

    def disks(self):
        """Returns all disks in the system, as visible from the AWS registry"""
        disks = set()
        for v in list(self._disks.values()):
            disks = disks.union([self.__disk_name(x) for x in v])
        return disks

    def root_device(self):
        """Returns the device being used for root data. Unlike root_disk(),
           which will return a device name (i.e. xvda), this function will return
           the full path to the root partition as returned by the AWS instance
           metadata registry"""
        return set(self._disks["root"])

    def root_disk(self):
        """Returns the disk used for the root partition"""
        return self.__disk_name(self._disks["root"][0])

    def non_root_disks(self):
        """Returns all attached disks but root. Include ephemeral and EBS devices"""
        return set(self._disks["ephemeral"] + self._disks["ebs"])

    @property
    def nvme_disk_count(self):
        return len(self.non_root_disks())

    def get_local_disks(self):
        """Returns all ephemeral disks. Include standard SSDs and NVMe"""
        return self._disks["ephemeral"]

    def get_remote_disks(self):
        """Returns all EBS disks"""
        return self._disks["ebs"]

    def public_ipv4(self):
        """Returns the public IPv4 address of this instance"""
        return self.__instance_metadata("public-ipv4")

    def private_ipv4(self):
        """Returns the private IPv4 address of this instance"""
        return self.__instance_metadata("local-ipv4")

    def is_vpc_enabled(self, nic='eth0'):
        mac = self.__mac_address(nic)
        mac_stat = self.__instance_metadata('network/interfaces/macs/{}'.format(mac))
        return True if re.search(r'^vpc-id$', mac_stat, flags=re.MULTILINE) else False

    @staticmethod
    def check():
        return run('/opt/scylladb/scylla-machine-image/scylla_ec2_check --nic eth0', shell=True)

    def io_setup(self):
        run('/opt/scylladb/scylla-machine-image/scylla_cloud_io_setup', check=True, shell=True)

    @property
    def user_data(self):
        base_contents = curl(self.META_DATA_BASE_URL).splitlines()
        if 'user-data' in base_contents:
            return curl(self.META_DATA_BASE_URL + 'user-data')
        else:
            return ''



def is_ec2():
    return aws_instance.is_aws_instance()

def is_gce():
    return gcp_instance.is_gce_instance()

def is_azure():
    return azure_instance.is_azure_instance()

def get_cloud_instance():
    if is_ec2():
        return aws_instance()
    elif is_gce():
        return gcp_instance()
    elif is_azure():
        return azure_instance()
    else:
        raise Exception("Unknown cloud provider! Only AWS/GCP/Azure supported.")


CONCOLORS = {'green': '\033[1;32m', 'red': '\033[1;31m', 'nocolor': '\033[0m'}


def colorprint(msg, **kwargs):
    fmt = dict(CONCOLORS)
    fmt.update(kwargs)
    print(msg.format(**fmt))

def is_redhat_variant():
    return 'rhel' in distro.like().split()
