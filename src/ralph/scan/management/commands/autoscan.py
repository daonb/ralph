#!/usr/bin/env python
# -*- coding: utf-8 -*-

"""Discovers machines in networks specified in the admin."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import textwrap

from optparse import make_option

import ipaddr

from django.core.management.base import BaseCommand

from ralph.discovery.models import DiscoveryQueue, DataCenter, Network
from ralph.scan.autoscan import (
    autoscan_address,
    autoscan_data_center,
    autoscan_network,
)
from ralph.scan.errors import Error
from ralph.scan.util import find_network


class Command(BaseCommand):
    """
    Runs an automatic pre-scan of an address, a network of addresses or all
    networks in a data center.
    """

    help = textwrap.dedent(__doc__).strip()
    option_list = BaseCommand.option_list + (
        make_option(
            '-n',
            '--networks',
            dest='network',
            action='store_true',
            default=False,
            help='Scan the specified networks (space delimited).',
        ),
        make_option(
            '-c',
            '--data-centers',
            dest='data_center',
            action='store_true',
            default=False,
            help='Scan all networks in the specified data centers (space '
                 'delimited).',
        ),
        make_option(
            '-q',
            '--queues',
            dest='queue',
            action='store_true',
            default=False,
            help='Scan all networks that use the specified worker queues ('
                 'space delimited).',
        ),
    )
    requires_model_validation = False

    def handle(self, *args, **kwargs):
        if sum([
            kwargs['network'],
            kwargs['data_center'],
            kwargs['queue']
        ]) > 1:
            raise SystemExit(
                "You can't mix networks, data centers and queues.",
            )
        if not args:
            raise SystemExit("Please specify the addresses to scan.")
        if kwargs['network']:
            try:
                networks = [
                    find_network(network_spec) for network_spec in args
                ]
                for network in networks:
                    autoscan_network(network)
            except (Error, Network.DoesNotExist) as e:
                raise SystemExit(e)
        elif kwargs['data_center']:
            try:
                data_centers = [
                    DataCenter.objects.get(name=name) for name in args
                ]
                for data_center in data_centers:
                    autoscan_data_center(data_center)
            except (Error, DataCenter.DoesNotExist) as e:
                raise SystemExit(e)
        elif kwargs['queue']:
            try:
                queues = [
                    DiscoveryQueue.objects.get(name=name) for name in args
                ]
                for queue in queues:
                    for network in queue.network_set.all():
                        autoscan_network(network)
            except (Error, DiscoveryQueue.DoesNotExist) as e:
                raise SystemExit(e)
        else:
            try:
                addresses = [str(ipaddr.IPAddress(ip)) for ip in args]
                for address in addresses:
                    autoscan_address(address)
            except (Error, ValueError) as e:
                raise SystemExit(e)
