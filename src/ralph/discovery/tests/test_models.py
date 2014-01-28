# -*- coding: utf-8 -*-

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

import datetime

from django.test import TestCase
from django.contrib.auth.models import User
from lck.django.tags.models import Tag, Taggable
import mock

from ralph.discovery.models import DeviceType, Device, UptimeSupport
from ralph.discovery.models_history import HistoryChange


class ModelsTest(TestCase):
    def test_device_create_empty(self):
        with self.assertRaises(ValueError):
            Device.create(model_name='xxx', model_type=DeviceType.unknown)

    def test_device_create_nomodel(self):
        with self.assertRaises(ValueError):
            Device.create(sn='xxx')

    def test_device_conflict(self):
        Device.create([('1', 'DEADBEEFCAFE', 0)],
                      model_name='xxx', model_type=DeviceType.rack_server)
        Device.create([('1', 'CAFEDEADBEEF', 0)],
                      model_name='xxx', model_type=DeviceType.rack_server)
        with self.assertRaises(ValueError):
            Device.create([('1', 'DEADBEEFCAFE', 0), ('2', 'CAFEDEADBEEF', 0)],
                          model_name='yyy', model_type=DeviceType.switch)

    def test_device_create_blacklist(self):
        ethernets = [
            ('1', 'DEADBEEFCAFE', 0),
            ('2', 'DEAD2CEFCAFE', 0),
        ]
        dev = Device.create(ethernets, sn='None',
                            model_name='xxx', model_type=DeviceType.unknown)

        self.assertEqual(dev.sn, None)
        macs = [e.mac for e in dev.ethernet_set.all()]
        self.assertEqual(macs, ['DEADBEEFCAFE'])

    def test_device_history(self):
        dev = Device.create(
            model_name='xxx',
            model_type=DeviceType.unknown,
            sn='xaxaxa',
            user='ralph',
        )
        dev.name = 'dev1'
        dev.save()
        history = HistoryChange.objects.all()
        self.assertEqual(history[0].field_name, 'id')
        self.assertEqual(history[0].new_value, '1')
        self.assertEqual(history[1].old_value, '')
        self.assertEqual(history[1].new_value, dev.name)
        self.assertEqual(history[1].new_value, 'dev1')
        dev_db = Device.objects.get(id=dev.id)
        self.assertEqual(dev_db.name, 'dev1')
        self.assertEqual(dev_db.sn, 'xaxaxa')

    def test_device_children(self):
        grandpapa = Device.create(name="grandpapa", sn="1",
                      model_name='xxx', model_type=DeviceType.rack_server)
        papa = Device.create(name="papa", parent=grandpapa, sn="2",
                      model_name='xxx', model_type=DeviceType.unknown)
        kid = Device.create(name="kid", parent=papa, sn="3",
                      model_name='xxx', model_type=DeviceType.unknown)
        self.assertEqual(sorted(grandpapa.get_all_children(), key=repr),
                         sorted([papa, kid], key=repr))

mock_now = lambda: datetime.datetime(2010,10,3,14,53,21)
class MockDateTime(datetime.datetime):
    @classmethod
    def now(cls):
        return mock_now() 

class UptimeSupportTest(TestCase):
    @mock.patch('ralph.discovery.models_device.datetime.datetime', MockDateTime)
    def test_uptime(self):
        class Model(UptimeSupport):
            pass
        m = Model()
        self.assertEqual(m.uptime, None)
        m.uptime = 132
        self.assertEqual(m.uptime, datetime.timedelta(seconds=132))

class TagUpdateTest(TestCase):
    @mock.patch('lck.django.common.models.now', mock_now)
    def create_device(self):
        return Device.create(
            model_name='xxx',
            model_type=DeviceType.unknown,
            sn='xaxaxa',
            user='ralph',
        )
    def test_add_delete_tag(self):
        dev = self.create_device()
        self.assertEqual(dev.modified, mock_now())
        user = User.objects.create_user(username="a user")
        dev.tag('tag',1, user)
        dev = Device.objects.get(pk=dev.id)
        self.assertTrue(datetime.datetime.now()-dev.modified < datetime.timedelta(seconds=1))
        # now, let's delete the tag
        Tag.objects.get(name='tag').delete()
        last_mod = dev.modified
        dev = Device.objects.get(pk=dev.id)
        self.assertTrue(dev.modified > last_mod)
