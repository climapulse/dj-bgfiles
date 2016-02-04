# -*- coding: utf-8 -*-
from bgfiles.models import FileRequest
from datetime import timedelta

from django.core.files.base import ContentFile
from django.test import TestCase, override_settings
from django.utils import timezone
import mock
import os
import time
from .utils import WithTempDir


class FileRequestManagerToHandleTest(TestCase):

    def test(self):
        now = timezone.now()
        # This one should be ignored
        FileRequest.objects.create(finished_at=now, requested_at=now)
        requests_to_handle = [
            FileRequest.objects.create(requested_at=now - timedelta(seconds=30)),
            FileRequest.objects.create(requested_at=now),
            FileRequest.objects.create(requested_at=now + timedelta(seconds=30)),
        ]
        results = list(FileRequest.objects.to_handle())
        self.assertEqual(3, len(results))
        self.assertEqual([req for req in requests_to_handle], results)


class FileRequestManagerRemoveExpiredTest(TestCase):

    def setUp(self):
        self.now = timezone.now()
        # This one should be ignored
        self.no_expiration = FileRequest.objects.create(expires_at=None, requested_at=self.now)
        self.expires_now = FileRequest.objects.create(expires_at=self.now, requested_at=self.now)
        self.treshold = self.now - timedelta(seconds=10)
        self.expired = [
            FileRequest.objects.create(expires_at=self.treshold - timedelta(seconds=300), requested_at=self.now),
            FileRequest.objects.create(expires_at=self.treshold - timedelta(seconds=30), requested_at=self.now),
            FileRequest.objects.create(expires_at=self.treshold, requested_at=self.now),
        ]

    def test(self):
        status, nr_deleted, total = FileRequest.objects.remove_expired(self.treshold)
        self.assertEqual(status, 'processed')
        self.assertEqual(nr_deleted, len(self.expired))
        self.assertEqual(nr_deleted, total)
        self.assertDeleted(self.expired)
        self.assertNotDeleted([self.expires_now, self.no_expiration])

    def test_max_items(self):
        status, nr_deleted, total = FileRequest.objects.remove_expired(self.treshold, max_items=1)
        self.assertEqual(status, 'max_items')
        self.assertEqual(nr_deleted, 1)
        self.assertEqual(total, len(self.expired))
        # The first request in expired should be the one that's deleted
        self.assertDeleted(self.expired[:1])
        self.assertNotDeleted(self.expired[1:] + [self.expires_now, self.no_expiration])

    def test_timeout(self):
        timeout = time.time()
        status, nr_deleted, total = FileRequest.objects.remove_expired(self.treshold, timeout=timeout)
        self.assertEqual(status, 'timeout')
        # Because we only check the timeout after the first run (what's the point otherwise?) we expect a single delete
        self.assertEqual(nr_deleted, 1)
        self.assertEqual(total, len(self.expired))
        # The first request in expired should be the one that's deleted
        self.assertDeleted(self.expired[:1])
        self.assertNotDeleted(self.expired[1:] + [self.expires_now, self.no_expiration])

    @mock.patch('bgfiles.models.time')
    def test_sleep(self, time_mock):
        sleep = 2.5
        status, nr_deleted, total = FileRequest.objects.remove_expired(self.treshold, sleep=sleep)
        self.assertEqual(status, 'processed')
        self.assertEqual(nr_deleted, len(self.expired))
        self.assertEqual(total, len(self.expired))
        self.assertDeleted(self.expired)
        self.assertNotDeleted([self.expires_now, self.no_expiration])
        # Verify sleep was called between requests
        time_mock.sleep.assert_called_with(sleep)
        self.assertEqual(len(self.expired) - 1, time_mock.sleep.call_count)

    def assertDeleted(self, requests):
        self.assertFalse(FileRequest.objects.filter(id__in=[r.id for r in requests]).exists())

    def assertNotDeleted(self, requests):
        self.assertEqual(len(requests), FileRequest.objects.filter(id__in=[r.id for r in requests]).count())


class FileRequestTest(WithTempDir, TestCase):

    def test_str(self):
        request = FileRequest(requested_at=timezone.now(), requester=None, file_type='report')
        expected = '{} requested at {} by {}'.format(request.file_type, request.requested_at, request.requester)
        self.assertEqual(expected, '%s' % request)

    def test_expire_in(self):
        request = FileRequest(requested_at=timezone.now(), requester=None, file_type='report')
        now = timezone.now()
        delta = timedelta(days=4, seconds=10)
        request.expire_in(delta, timestamp=now)
        self.assertEqual(request.expires_at, now + delta)
        request.expire_in(delta)
        self.assertTrue(request.expires_at >= now + delta)

    def test_attach_file_and_delete(self):
        request = FileRequest(requested_at=timezone.now(), requester=None, file_type='report')
        request.save()
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL=''):
            contents = ContentFile('something special')
            request.attach_file(contents)
            request.save()
            self.assertTrue(request.finished_at)
            path = request.filehandle.path
            self.assertTrue(os.path.isfile(path))
            request.delete()
            self.assertFalse(os.path.isfile(path))

    def test_attach_file_with_overrides(self):
        values = {
            'filename': ('', 'abc', 'def', ''),
            'content_type': ('', '', 'xyz', 'oh'),
            'size': (None, 5, 0, 20)
        }
        request = FileRequest(requested_at=timezone.now(), requester=None, file_type='report')
        request.filename = 'ohboy'
        request.save()
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL=''):
            contents = ContentFile('something special')
            for i in range(4):
                kwargs = {'contents': contents}
                old_values = {}
                new_values = {}
                for field, value_list in values.items():
                    old_values[field] = getattr(request, field)
                    new_values[field] = value_list[i]
                    kwargs[field] = value_list[i]
                request.attach_file(**kwargs)
                for field, old_value in old_values.items():
                    new_value = new_values[field]
                    if new_value:
                        self.assertEqual(new_value, getattr(request, field))
                    else:
                        self.assertEqual(old_value, getattr(request, field))
