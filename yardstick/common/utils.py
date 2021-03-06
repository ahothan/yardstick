# Copyright 2013: Mirantis Inc.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

# yardstick comment: this is a modified copy of rally/rally/common/utils.py

from __future__ import absolute_import
from __future__ import print_function

import errno
import logging
import os
import subprocess
import sys
import collections
import socket
import random
from functools import reduce
from contextlib import closing

import yaml
import six
from flask import jsonify
from six.moves import configparser
from oslo_utils import importutils
from oslo_serialization import jsonutils

import yardstick

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


# Decorator for cli-args
def cliargs(*args, **kwargs):
    def _decorator(func):
        func.__dict__.setdefault('arguments', []).insert(0, (args, kwargs))
        return func
    return _decorator


def itersubclasses(cls, _seen=None):
    """Generator over all subclasses of a given class in depth first order."""

    if not isinstance(cls, type):
        raise TypeError("itersubclasses must be called with "
                        "new-style classes, not %.100r" % cls)
    _seen = _seen or set()
    try:
        subs = cls.__subclasses__()
    except TypeError:   # fails only when cls is type
        subs = cls.__subclasses__(cls)
    for sub in subs:
        if sub not in _seen:
            _seen.add(sub)
            yield sub
            for sub in itersubclasses(sub, _seen):
                yield sub


def try_append_module(name, modules):
    if name not in modules:
        modules[name] = importutils.import_module(name)


def import_modules_from_package(package):
    """Import modules from package and append into sys.modules

    :param: package - Full package name. For example: rally.deploy.engines
    """
    path = [os.path.dirname(yardstick.__file__), ".."] + package.split(".")
    path = os.path.join(*path)
    for root, dirs, files in os.walk(path):
        for filename in files:
            if filename.startswith("__") or not filename.endswith(".py"):
                continue
            new_package = ".".join(root.split(os.sep)).split("....")[1]
            module_name = "%s.%s" % (new_package, filename[:-3])
            try:
                try_append_module(module_name, sys.modules)
            except ImportError:
                logger.exception("unable to import %s", module_name)


def parse_yaml(file_path):
    try:
        with open(file_path) as f:
            value = yaml.safe_load(f)
    except IOError:
        return {}
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise
    else:
        return value


def get_param(key, default=''):

    conf_file = os.environ.get('CONF_FILE', '/etc/yardstick/yardstick.yaml')

    conf = parse_yaml(conf_file)
    try:
        return reduce(lambda a, b: a[b], key.split('.'), conf)
    except KeyError:
        if not default:
            raise
        return default


def makedirs(d):
    try:
        os.makedirs(d)
    except OSError as e:
        if e.errno != errno.EEXIST:
            raise


def remove_file(path):
    try:
        os.remove(path)
    except OSError as e:
        if e.errno != errno.ENOENT:
            raise


def execute_command(cmd):
    exec_msg = "Executing command: '%s'" % cmd
    logger.debug(exec_msg)

    output = subprocess.check_output(cmd.split()).split(os.linesep)

    return output


def source_env(env_file):
    p = subprocess.Popen(". %s; env" % env_file, stdout=subprocess.PIPE,
                         shell=True)
    output = p.communicate()[0]
    env = dict((line.split('=', 1) for line in output.splitlines()))
    os.environ.update(env)
    return env


def read_json_from_file(path):
    with open(path, 'r') as f:
        j = f.read()
    # don't use jsonutils.load() it conflicts with already decoded input
    return jsonutils.loads(j)


def write_json_to_file(path, data, mode='w'):
    with open(path, mode) as f:
        jsonutils.dump(data, f)


def write_file(path, data, mode='w'):
    with open(path, mode) as f:
        f.write(data)


def parse_ini_file(path):
    parser = configparser.ConfigParser()

    try:
        files = parser.read(path)
    except configparser.MissingSectionHeaderError:
        logger.exception('invalid file type')
        raise
    else:
        if not files:
            raise RuntimeError('file not exist')

    try:
        default = {k: v for k, v in parser.items('DEFAULT')}
    except configparser.NoSectionError:
        default = {}

    config = dict(DEFAULT=default,
                  **{s: {k: v for k, v in parser.items(
                      s)} for s in parser.sections()})

    return config


def get_port_mac(sshclient, port):
    cmd = "ifconfig |grep HWaddr |grep %s |awk '{print $5}' " % port
    status, stdout, stderr = sshclient.execute(cmd)

    if status:
        raise RuntimeError(stderr)
    return stdout.rstrip()


def get_port_ip(sshclient, port):
    cmd = "ifconfig %s |grep 'inet addr' |awk '{print $2}' " \
        "|cut -d ':' -f2 " % port
    status, stdout, stderr = sshclient.execute(cmd)

    if status:
        raise RuntimeError(stderr)
    return stdout.rstrip()


def flatten_dict_key(data):
    next_data = {}

    # use list, because iterable is too generic
    if not any(isinstance(v, (collections.Mapping, list))
               for v in data.values()):
        return data

    for k, v in six.iteritems(data):
        if isinstance(v, collections.Mapping):
            for n_k, n_v in six.iteritems(v):
                next_data["%s.%s" % (k, n_k)] = n_v
        # use list because iterable is too generic
        elif isinstance(v, list):
            for index, item in enumerate(v):
                next_data["%s%d" % (k, index)] = item
        else:
            next_data[k] = v

    return flatten_dict_key(next_data)


def translate_to_str(obj):
    if isinstance(obj, collections.Mapping):
        return {str(k): translate_to_str(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [translate_to_str(ele) for ele in obj]
    elif isinstance(obj, six.text_type):
        return str(obj)
    return obj


def result_handler(status, data):
    result = {
        'status': status,
        'result': data
    }
    return jsonify(result)


def change_obj_to_dict(obj):
    dic = {}
    for k, v in vars(obj).items():
        try:
            vars(v)
        except TypeError:
            dic.update({k: v})
    return dic


def set_dict_value(dic, keys, value):
    return_dic = dic

    for key in keys.split('.'):

        return_dic.setdefault(key, {})
        if key == keys.split('.')[-1]:
            return_dic[key] = value
        else:
            return_dic = return_dic[key]
    return dic


def get_free_port(ip):
    with closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as s:
        while True:
            port = random.randint(5000, 10000)
            if s.connect_ex((ip, port)) != 0:
                return port
