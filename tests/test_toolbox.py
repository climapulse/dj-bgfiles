# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from bgfiles import toolbox
from bgfiles.models import FileRequest
from django.conf import settings
from django.contrib.auth.models import User
from django.core.files.base import ContentFile
from django.core.signing import BadSignature
from django.http import Http404
from django.utils import six
from django.test import SimpleTestCase, TestCase, override_settings
import os
import tempfile
from .utils import WithTempDir


class GetDefaultSignerTest(SimpleTestCase):

    def test(self):
        signer = toolbox.get_default_signer()
        self.assertEqual(signer.key, settings.SECRET_KEY)
        self.assertEqual(signer.salt, toolbox.Signer.DEFAULT_SALT)
        self.assertEqual(signer.serializer, toolbox.Signer.DEFAULT_SERIALIZER)
        self.assertEqual(signer.max_age, 86400)

    def test_overridden(self):
        signer = toolbox.Signer()
        with override_settings(BGFILES_DEFAULT_SIGNER=signer):
            self.assertTrue(toolbox.get_default_signer() is signer)

    def test_overridden_settings(self):
        my_key = 'abclkdjsldkjsldkjsd__*((#*))'
        my_salt = 'wiouoegwgr'
        my_serializer_class = type(str('MySerializer'), (toolbox.JSONSerializer,), {})
        my_max_age = 3540
        kwargs = {
            'BGFILES_DEFAULT_KEY': my_key,
            'BGFILES_DEFAULT_SALT': my_salt,
            'BGFILES_DEFAULT_SERIALIZER': my_serializer_class,
            'BGFILES_DEFAULT_MAX_AGE': my_max_age
        }
        with override_settings(**kwargs):
            signer = toolbox.get_default_signer()
        self.assertEqual(signer.key, my_key)
        self.assertEqual(signer.salt, my_salt)
        self.assertEqual(signer.serializer, my_serializer_class)
        self.assertEqual(signer.max_age, my_max_age)


class SignerLoadsAndDumpsTest(SimpleTestCase):

    def test(self):
        signer = toolbox.get_default_signer()
        data_in = {'a': 1, 'b': 3, 'www': {'abc': ['y', 'z']}}
        token = signer.dump(data_in)
        data_out = signer.load(token)
        self.assertDictEqual(data_in, data_out)


class AddRequestTest(TestCase):

    def test(self):
        criteria = 'abc'
        request = toolbox.add_request(criteria)
        self.assertEqual(criteria, request.criteria)
        self.assertTrue(request.requested_at)
        self.assertFalse(request.file_type)
        self.assertFalse(request.requester)
        self.assertFalse(request.content_type)
        self.assertTrue(request.id)
        content_type = 'text/csv'
        request = toolbox.add_request(criteria, content_type=content_type)
        self.assertEqual(criteria, request.criteria)
        self.assertEqual(content_type, request.content_type)
        self.assertTrue(request.requested_at)
        self.assertFalse(request.file_type)
        self.assertFalse(request.requester)
        file_type = 'some-report'
        request = toolbox.add_request(criteria, content_type=content_type, file_type=file_type)
        self.assertEqual(criteria, request.criteria)
        self.assertEqual(content_type, request.content_type)
        self.assertEqual(file_type, request.file_type)
        self.assertTrue(request.requested_at)
        self.assertFalse(request.requester)
        requester = User.objects.create_user('something', 'mail@example.com', 'abc')
        request = toolbox.add_request(criteria, content_type=content_type, file_type=file_type, requester=requester)
        self.assertEqual(criteria, request.criteria)
        self.assertEqual(content_type, request.content_type)
        self.assertEqual(file_type, request.file_type)
        self.assertEqual(requester, request.requester)
        self.assertTrue(request.requested_at)


class AttachFileTest(WithTempDir, TestCase):

    def test(self):
        request = toolbox.add_request('abc')
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL=''):
            contents = ContentFile('something special')
            toolbox.attach_file(request, contents, 'something.txt', 'text/plain')
            path = request.filehandle.path
            self.assertTrue(os.path.isfile(path))
            request.delete()
            self.assertFalse(os.path.isfile(path))

    def test_attach_local_file(self):
        fh, temppath = tempfile.mkstemp('test')
        os.close(fh)
        with open(temppath, 'w') as fh:
            fh.write(six.text_type('something special'))
        request = toolbox.add_request('abc')
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL=''):
            toolbox.attach_local_file(request, temppath, 'something.txt', 'text/plain')
            path = request.filehandle.path
            self.assertTrue(os.path.isfile(path))
            request.delete()
            self.assertFalse(os.path.isfile(path))


class CreateTokenTest(TestCase):

    def test(self):
        requester = User.objects.create_user('ownow', 'mail@example.com', 'mypassword')
        request = toolbox.add_request('abc', requester=requester)
        token = toolbox.create_token(request)
        data = toolbox.get_default_signer().load(token)
        self.assertEquals(data.get('id'), '%s' % request.id)
        self.assertEquals(data.get('requester'), requester.id)
        # Now with additional data
        additional_data = {'abc': 123, 'z': ['y', 'z', 1]}
        token = toolbox.create_token(request, data=additional_data)
        data = toolbox.get_default_signer().load(token)
        additional_data['id'] = '%s' % request.id
        additional_data['requester'] = requester.id
        self.assertDictEqual(data, additional_data)

    def test_missing_requester(self):
        request = toolbox.add_request('abc')
        self.assertRaises(RuntimeError, toolbox.create_token, request)

    def test_general(self):
        requester = User.objects.create_user('ownow', 'mail@example.com', 'mypassword')
        request = toolbox.add_request('abc', requester=requester)
        token = toolbox.create_general_token(request)
        data = toolbox.get_default_signer().load(token)
        self.assertEquals(data.get('id'), '%s' % request.id)
        self.assertFalse('requester' in data)
        # Now with additional data
        additional_data = {'abc': 123, 'z': ['y', 'z', 1]}
        token = toolbox.create_general_token(request, data=additional_data)
        data = toolbox.get_default_signer().load(token)
        additional_data['id'] = '%s' % request.id
        self.assertDictEqual(data, additional_data)

    def test_general_does_not_require_requester(self):
        request = toolbox.add_request('abc')
        toolbox.create_general_token(request)


class DecodeTest(TestCase):

    def test(self):
        requester = User.objects.create_user('ownow', 'mail@example.com', 'mypassword')
        request = toolbox.add_request('abc', requester=requester)
        token = toolbox.create_token(request)
        # Clear the requester
        request.requester = None
        request.save()
        self.assertRaises(FileRequest.DoesNotExist, toolbox.decode, token, require_requester=True)
        request.requester = requester
        request.save()
        found, data = toolbox.decode(token, require_requester=True)
        self.assertEqual(found, request)

    def test_general(self):
        request = toolbox.add_request('abc')
        token = toolbox.create_general_token(request)
        request.delete()
        self.assertRaises(FileRequest.DoesNotExist, toolbox.decode, token, require_requester=False)

    def test_requester_required_but_not_present(self):
        request = toolbox.add_request('abc')
        token = toolbox.create_general_token(request)
        request.delete()
        self.assertRaises(BadSignature, toolbox.decode, token, require_requester=True)


class ServeTest(WithTempDir, TestCase):

    def test_no_file_yet(self):
        request = toolbox.add_request('abc')
        self.assertRaises(Http404, toolbox.serve, request)
        to_raise = ValueError
        self.assertRaises(to_raise, toolbox.serve, request, raise_on_missing=to_raise)

    def test(self):
        request = toolbox.add_request('abc')
        with override_settings(MEDIA_ROOT=self.tempdir, MEDIA_URL=''):
            contents = ContentFile('something special')
            toolbox.attach_file(request, contents, 'something.txt')
            response = toolbox.serve(request)
            self.assertEqual(response['Content-Type'], 'application/octet-stream')
            self.assertEqual(response['Content-Disposition'], 'attachment; filename="something.txt"')
            self.assertEqual(response.content, b'something special')
            response = toolbox.serve(request, default_content_type='text/plain')
            self.assertEqual(response['Content-Type'], 'text/plain')
            self.assertEqual(response.content, b'something special')
            self.assertEqual(response['Content-Disposition'], 'attachment; filename="something.txt"')
            request.filename = ''
            request.save()
            response = toolbox.serve(request, default_content_type='text/plain')
            self.assertEqual(response['Content-Type'], 'text/plain')
            self.assertEqual(response.content, b'something special')
            self.assertFalse(response.get('Content-Disposition'))
