# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import re

from django.conf import settings

from ralph.discovery.hardware import normalize_wwn
from ralph.discovery.models import DeviceType
from ralph.scan.errors import ConnectionError, NoMatchError
from ralph.scan.plugins import get_base_result_template
from ralph.util import network


SETTINGS = settings.SCAN_PLUGINS.get(__name__, {})
_3PAR_RE = re.compile(r'^\s+ID\s+-+Name-+\s+-+Model-+')


def _connect_ssh(ip_address, user, password):
    if not network.check_tcp_port(ip_address, 22):
        raise ConnectionError('Port 22 closed on a 3PAR server.')
    return network.connect_ssh(ip_address, user, password)


def _handle_shares(shares):
    return [
        {
            'model_name': '3PAR %s disk share' % share_type,
            'label': label,
            'share_id': share_id,
            'snapshot_size': snapshot_size,
            'size': size,
            'full': full,
            'serial_number': normalize_wwn(wwn),
        } for share_id, (label, wwn, snapshot_size, size, share_type,
                         speed, full) in shares.iteritems()
    ]


def _ssh_3par(ip_address, user, password):
    ssh = _connect_ssh(ip_address, user, password)
    try:
        stdin, stdout, stderr = ssh.exec_command("showsys")
        lines = list(stdout.readlines())
        if not _3PAR_RE.match(lines[1]):
            raise NoMatchError('Not a 3PAR.')
        line = lines[-1]
        name = line[5:15].strip()
        model_name = line[16:28].strip()
        sn = line[29:37].strip()
        stdin, stdout, stderr = ssh.exec_command(
            "showvv -showcols "
            "Id,Name,VV_WWN,Snp_RawRsvd_MB,Usr_RawRsvd_MB,Prov",
        )
        shares = {}
        for line in list(stdout.readlines()):
            if line.strip().startswith('Id'):
                continue
            if line.startswith('----'):
                break
            share_id, share_name, wwn, snapshot_size, size, prov = line.split(
                None,
                5,
            )
            if '--' in size or '--' in snapshot_size:
                continue
            share_id = int(share_id)
            if share_id == 0:
                continue
            snapshot_size = int(snapshot_size)
            size = int(size)
            stdin, stdout, stderr = ssh.exec_command(
                "showld -p -vv %s" % share_name,
            )
            lines = list(stdout.readlines())
            (
                logical_id,
                logical_name,
                preserve,
                disk_type,
                speed,
            ) = lines[1].split(None, 5)
            speed = int(speed) * 1000
            shares[share_id] = (
                share_name,
                wwn,
                snapshot_size,
                size,
                disk_type,
                speed,
                prov.strip() == 'full',
            )
    finally:
        ssh.close()
    device_info = {
        'type': DeviceType.storage.raw,
        'model_name': '3PAR %s' % model_name,
        'hostname': name,
        'serial_number': sn,
        'management_ip_addresses': [ip_address],
    }
    shares = _handle_shares(shares)
    if shares:
        device_info['disk_exports'] = shares
    return device_info


def scan_address(ip_address, **kwargs):
    user = SETTINGS.get('user')
    password = SETTINGS.get('password')
    messages = []
    result = get_base_result_template('ssh_3par', messages)
    if not user or not password:
        result['status'] = 'error'
        messages.append(
            'Not configured. Set SSH_3PAR_USER and SSH_3PAR_PASSWORD in your '
            'configuration file.',
        )
    else:
        device_info = _ssh_3par(ip_address, user, password)
        result.update({
            'status': 'success',
            'device': device_info,
        })
    return device_info

