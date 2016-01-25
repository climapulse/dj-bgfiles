# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from bgfiles import toolbox
from bgfiles.patterns import registry
from django.test import TestCase
from django.utils import timezone


class SimpleHandler(object):
    handled = []

    @classmethod
    def handle(cls, request):
        cls.handled.append(request)


class RegistryTest(TestCase):

    def setUp(self):
        self.original_handlers = registry.handlers.copy()
        registry.handlers.clear()
        SimpleHandler.handled = []

    def tearDown(self):
        registry.handlers.clear()
        registry.handlers.update(self.original_handlers)

    def test(self):
        registry.register(SimpleHandler, ['something'])
        request = toolbox.add_request('abc', file_type='something')
        self.assertTrue(registry.dispatch(request.id))
        self.assertEqual([request], SimpleHandler.handled)

    def test_no_handler(self):
        request = toolbox.add_request('abc')
        self.assertRaises(KeyError, registry.dispatch, request.id)
        registry.register(SimpleHandler, ['something'])
        self.assertRaises(KeyError, registry.dispatch, request.id)

    def test_already_finished(self):
        registry.register(SimpleHandler, ['something'])
        request = toolbox.add_request('abc', file_type='something')
        request.finished_at = timezone.now()
        request.save()
        self.assertFalse(registry.dispatch(request.id))
        self.assertEqual(0, len(SimpleHandler.handled))
