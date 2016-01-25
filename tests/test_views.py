# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from bgfiles import toolbox
from bgfiles.views import serve_file, SuspiciousToken, SignatureHasExpired, UserIsNotRequester
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.files.base import ContentFile
from django.core.signing import SignatureExpired
from django.http import Http404
from django.test import SimpleTestCase, TestCase, RequestFactory, override_settings
import mock
from .utils import WithTempDir


class VerifyExceptionTypeTest(SimpleTestCase):

    def test(self):
        self.assertTrue(issubclass(SuspiciousToken, SuspiciousOperation))
        self.assertTrue(issubclass(SignatureHasExpired, PermissionDenied))
        self.assertTrue(issubclass(UserIsNotRequester, PermissionDenied))


class ServeFileTest(WithTempDir, TestCase):

    def setUp(self):
        self.factory = RequestFactory()
        self.user = User.objects.create_user('abc', 'mail@example.com', 'abc')

    def test_request_does_not_exist(self):
        request = toolbox.add_request('abc', requester=self.user)
        token = toolbox.create_token(request)
        request.delete()
        http_request = self.factory.get('/something')
        http_request.user = self.user
        self.assertRaises(Http404, serve_file, http_request, token)

    @mock.patch('bgfiles.views.toolbox.decode')
    def test_token_expired(self, decode_mock):
        decode_mock.side_effect = SignatureExpired
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL='/'):
            request = toolbox.add_request('abc', requester=self.user)
            toolbox.attach_file(request, ContentFile(b'abc'))
            token = toolbox.create_token(request)
            http_request = self.factory.get('/something')
            http_request.user = self.user
            self.assertRaises(SignatureHasExpired, serve_file, http_request, token)

    def test_invalid_token(self):
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL='/'):
            request = toolbox.add_request('abc', requester=self.user)
            toolbox.attach_file(request, ContentFile(b'abc'))
            token = toolbox.create_token(request)
            http_request = self.factory.get('/something')
            http_request.user = self.user
            self.assertRaises(SuspiciousToken, serve_file, http_request, token + 'a')

    def test_other_user(self):
        other_user = User.objects.create_user('oho', 'mymail@example.com', 'nono')
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL='/'):
            request = toolbox.add_request('abc', requester=self.user)
            toolbox.attach_file(request, ContentFile(b'abc'))
            token = toolbox.create_token(request)
            http_request = self.factory.get('/something')
            http_request.user = other_user
            self.assertRaises(UserIsNotRequester, serve_file, http_request, token)

    def test_other_user_with_no_verification(self):
        other_user = User.objects.create_user('oho', 'mymail@example.com', 'nono')
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL='/'):
            request = toolbox.add_request('abc', requester=self.user)
            toolbox.attach_file(request, ContentFile(b'abc'))
            token = toolbox.create_token(request)
            http_request = self.factory.get('/something')
            http_request.user = other_user
            response = serve_file(http_request, token, verify_requester=False)
            self.assertEqual(response.status_code, 200)

    def test_other_user_with_general_token(self):
        other_user = User.objects.create_user('oho', 'mymail@example.com', 'nono')
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL='/'):
            request = toolbox.add_request('abc', requester=self.user)
            toolbox.attach_file(request, ContentFile(b'abc'))
            token = toolbox.create_general_token(request)
            http_request = self.factory.get('/something')
            http_request.user = other_user
            # With no verification and no requester required
            response = serve_file(http_request, token, require_requester=False, verify_requester=False)
            self.assertEqual(response.status_code, 200)
            # Now try with simply not requiring the requester
            http_request.user = other_user
            self.assertRaises(UserIsNotRequester, serve_file, http_request, token, require_requester=False)
            # Now try with requiring the requester but not verifying
            http_request.user = other_user
            self.assertRaises(SuspiciousToken, serve_file, http_request, token, verify_requester=False)
