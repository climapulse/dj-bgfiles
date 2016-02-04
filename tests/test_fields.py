# -*- coding: utf-8 -*-
from bgfiles.fields import get_storage, get_upload_to
from django.test import SimpleTestCase, override_settings


class FileRequestSettingsTest(SimpleTestCase):

    def test_get_storage_default(self):
        self.assertTrue(get_storage() is None)

    def test_get_storage_overridden(self):
        sentinel = object()
        with override_settings(BG_FILES_STORAGE=sentinel):
            self.assertTrue(get_storage() is sentinel)

    def test_get_upload_to_default(self):
        self.assertEqual('', get_upload_to())

    def test_get_upload_to_overridden(self):
        upload_dir = '/oh/my/temp/'
        with override_settings(BG_FILES_UPLOAD_TO=upload_dir):
            self.assertEqual(upload_dir, get_upload_to())
