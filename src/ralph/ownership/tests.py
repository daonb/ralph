from __future__ import absolute_import
import mock

from django.test import TestCase
from django.contrib.auth.models import User

from ralph.discovery.models import Device
from . import models
from .models import Ownership

class SimpleTest(TestCase):
    def setUp(self):
        self.dev1 = Device.objects.create(name="dev1")
        self.dev2 = Device.objects.create(name="dev2")
        self.user1 = User.objects.create(username="user1")
        self.user2 = User.objects.create(username="user2")

    def test_default_owner(self):
        self.assertIsNone(Ownership.objects.get_owner(self.dev1))

    def test_grant(self):
        Ownership.objects.grant(self.dev1, self.user1)
        self.assertEquals(Ownership.objects.get_owner(self.dev1), self.user1)
        Ownership.objects.release(self.dev1)
        self.assertIsNone(Ownership.objects.get_owner(self.dev1))

    def test_release(self):
        Ownership.objects.grant(self.dev1, self.user1)
        self.assertEquals(Ownership.objects.get_owner(self.dev1), self.user1)
        Ownership.objects.grant(self.dev1, self.user2)
        self.assertEquals(Ownership.objects.get_owner(self.dev1), self.user2)
        Ownership.objects.release(self.dev1)
        self.assertEquals(Ownership.objects.get_owner(self.dev1), self.user1)
        Ownership.objects.release(self.dev1)
        self.assertIsNone(Ownership.objects.get_owner(self.dev1))

    def test_release_to(self):
        Ownership.objects.grant(self.dev1, self.user1)
        Ownership.objects.assign_to(self.dev1, self.user2)
        self.assertEquals(Ownership.objects.get_owner(self.dev1), self.user2)
        Ownership.objects.release(self.dev1)
        self.assertIsNone(Ownership.objects.get_owner(self.dev1))

def TimedTest(TestCase):
    def setUp(self):
        datetime_patcher = mock.patch.object(

            models.datetime, 'datetime',

            mock.Mock(wraps=datetime.datetime)

        )

        mocked_datetime = datetime_patcher.start()

        self.addCleanup(datetime_patcher.stop)

    def test_timed_grant():
        Ownership.objects.grant(self.dev1, self.user1, datetime.datetime(2005, 1, 18, 12))
        mocked_datetime.now.return_value = datetime.datetime(2005, 1, 18, 11,)
        Ownership.objects.update()
        self.assertEquals(Ownership.objects.get_owner(self.dev1), self.user2)
        self.assertEquals(Ownership.objects.time_left(self.dev1), datetime.timedelta(seconds=3600))
        mocked_datetime.now.return_value = datetime.datetime(2005, 1, 18, 12,1,)
        Ownership.objects.update()
        self.assertIsNone(Ownership.objects.get_owner(self.dev1))
        self.assertIsNone(Ownership.objects.time_left(self.dev1))
