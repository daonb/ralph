# -*- coding: utf-8 -*-

"""
Scan all existing and not dead IP addresses from specified networks or data
centers. This Scan tries to extract all possible data from all available
plugins. It also calculates checksum from plugins results. This checksum is
usefull to detect possible changes on devices.
"""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import copy
import datetime
import hashlib
import json
import logging

import django_rq
import rq

from django.conf import settings
from django.utils.importlib import import_module

from ralph.discovery.models import IPAddress, Network
from ralph.scan.errors import NoQueueError
from ralph.scan.models import ScanSummary


logger = logging.getLogger("SCAN")
SCAN_LOG_DIRECTORY = getattr(settings, 'SCAN_LOG_DIRECTORY', None)


def scan_address(ip_address, plugins, network=None):
    """Queue scan on the specified address."""

    if not network:
        try:
            network = Network.from_ip(ip_address.address)
        except IndexError:
            raise NoQueueError(
                "Address {0} doesn't belong to any configured "
                "network.".format(ip_address.address),
            )
    if not network.queue:
        raise NoQueueError(
            "The network {0} has no discovery queue.".format(network),
        )
    queue = django_rq.get_queue(network.queue.name)
    job = queue.enqueue_call(
        func=scan_address_job,
        args=(
            ip_address,
            plugins,
        ),
        kwargs={
            'snmp_community': ip_address.snmp_community,
            'snmp_version': ip_address.snmp_version,
            'http_family': ip_address.http_family,
            'snmp_name': ip_address.snmp_name,
        },
        timeout=300,
        result_ttl=86400,
    )
    return job


def scan_network(network, plugins):
    """Queue scan of a entire network on the right worker."""

    for address in network.network.iterhosts():
        try:
            # scan only exists and not dead IP addresses
            ip_address = IPAddress.objects.get(
                address=address,
                dead_ping_count__lte=settings.DEAD_PING_COUNT,
            )
        except IPAddress.DoesNotExist:
            continue
        else:
            scan_address(ip_address, plugins, network)


def scan_data_center(data_center, plugins):
    """Queue scan of all scannable networks in the data center."""

    for network in data_center.network_set.exclude(queue=None):
        scan_network(network, plugins)


def _run_plugins(address, plugins, job, **kwargs):
    results = {}
    job.meta['messages'] = []
    job.meta['finished'] = []
    job.meta['status'] = {}
    for plugin_name in plugins:
        message = "Running plugin %s." % plugin_name
        job.meta['messages'].append((address, plugin_name, 'info', message))
        job.save()
        try:
            module = import_module(plugin_name)
        except ImportError as e:
            message = 'Failed to import: %s.' % e
            job.meta['messages'].append(
                (address, plugin_name, 'error', message),
            )
            job.meta['status'][plugin_name] = 'error'
        else:
            try:
                result = module.scan_address(address, **kwargs)
            except Exception as e:
                name = plugin_name.split(".")[-1]
                msg = "Exception occured in plugin {} and address {}".format(
                    name,
                    address,
                )
                logger.exception(msg)
                result = {
                    'status': 'error',
                    'date': datetime.datetime.now().strftime(
                        '%Y-%m-%d %H:%M:%S',
                    ),
                    'plugin': name,
                    'messages': [msg, unicode(e.message)],
                }
            results[plugin_name] = result
            for message in result.get('messages', []):
                job.meta['messages'].append(
                    (address, plugin_name, 'warning', message),
                )
            job.meta['status'][plugin_name] = result.get('status', 'success')
        job.meta['finished'].append(plugin_name)
        job.save()
    return results


def _get_ip_addresses_from_results(results):
    """
    Returns list of IPAddress instances that are matched from inside scan
    results source addresses.
    """

    ip_addresses = set()
    for plugin_name, plugin_results in results.iteritems():
        # Only system ip addresses. This function will be used only with API
        # and only system ip addresses will be possible.
        device = plugin_results.get('device')
        if not device:
            continue
        ip_addresses |= set(device.get('system_ip_addresses', []))
    result = []
    for address in ip_addresses:
        ip_address, created = IPAddress.concurrent_get_or_create(
            address=address,
        )
        result.append(ip_address)
    return result


def _get_cleaned_results(data):
    UNNECESSARY_KEYS = set(['status', 'date', 'messages'])
    data = copy.deepcopy(data)
    for plugin_name, plugin_results in data.iteritems():
        for key in UNNECESSARY_KEYS:
            plugin_results.pop(key, None)
    return data


def _get_results_checksum(data):
    return hashlib.md5(json.dumps(data, sort_keys=True)).hexdigest()


def _scan_postprocessing(results, job, ip_address=None):
    """
    Postprocessing is an act of calculation checksums on scan results, and
    maintenance RQ jobs.
    """

    if any((
        'messages' not in job.meta,
        'finished' not in job.meta,
        'status' not in job.meta,
    )):
        job.meta['messages'] = []
        job.meta['finished'] = []
        job.meta['status'] = {}
        job.save()
    # get connected ip_address
    if not ip_address:
        ip_addresses = _get_ip_addresses_from_results(results)
        try:
            ip_address = ip_addresses[0]
        except IndexError:
            return
    # get (and update) or create scan_summary
    old_job = None
    if ip_address.scan_summary:
        scan_summary = ip_address.scan_summary
        try:
            old_job = rq.job.Job.fetch(
                scan_summary.job_id,
                django_rq.get_connection(),
            )
        except rq.exceptions.NoSuchJobError:
            pass
        else:
            if 'messages' in old_job.meta and not job.meta['messages']:
                job.meta['messages'] = old_job.meta['messages']
            for plugin in old_job.meta.get('finished', []):
                if plugin not in job.meta['finished']:
                    job.meta['finished'].append(plugin)
            for plugin, status in old_job.meta.get('status', {}).iteritems():
                if plugin not in job.meta['status']:
                    job.meta['status'][plugin] = status
            job.save()
        scan_summary.job_id = job.id
    else:
        scan_summary, created = ScanSummary.concurrent_get_or_create(
            job_id=job.id,
        )
        ip_address.scan_summary = scan_summary
    # update exists results data
    if old_job:
        updated_results = old_job.result
        for plugin_name, plugin_results in results.iteritems():
            updated_results[plugin_name] = plugin_results
            if plugin_name not in job.meta['finished']:
                job.meta['finished'].append(plugin_name)
            if plugin_name not in job.meta['status']:
                job.meta['status'][plugin_name] = plugin_results['status']
        job.save()
        results.update(updated_results)
    # calculate new checksum
    cleaned_results = _get_cleaned_results(results)
    checksum = _get_results_checksum(cleaned_results)
    job.meta['results_checksum'] = checksum
    job.save()
    # calculate new status
    if all((
        checksum != scan_summary.previous_checksum,
        checksum != scan_summary.false_positive_checksum,
    )):
        job.meta['changed'] = True
    else:
        job.meta['changed'] = False
        scan_summary.false_positive_checksum = None
    job.save()
    scan_summary.save()
    ip_address.save()
    # cancel old job (if exists)
    if old_job:
        rq.cancel_job(old_job.id, django_rq.get_connection())


def scan_address_job(ip_address=None, plugins=None, results=None, **kwargs):
    """
    The function that is actually running on the worker.
    """

    job = rq.get_current_job()
    available_plugins = getattr(settings, 'SCAN_PLUGINS', {}).keys()
    if not plugins:
        plugins = available_plugins
    run_postprocessing = not (set(available_plugins) - set(plugins))
    if ip_address and plugins:
        results = _run_plugins(ip_address.address, plugins, job, **kwargs)
    if run_postprocessing:
        _scan_postprocessing(results, job, ip_address)
    return results

