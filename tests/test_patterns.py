# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from bgfiles.models import FileRequest
from bgfiles.patterns import (Dataset, InvalidCriteria, InvalidForm, QueryDictCriteriaWithRequester,
                              QueryDictCriteria, Criteria, SimplePattern)
from django.contrib.auth.models import User
from django.test import RequestFactory, SimpleTestCase


class VerifyExceptionsTest(SimpleTestCase):

    def test(self):
        self.assertTrue(issubclass(InvalidForm, InvalidCriteria))

    def test_invalid_form(self):
        form = object()
        e = InvalidForm('Oh no!', form=form)
        self.assertEqual(e.form, form)


class QueryDictCriteriaWithRequesterTest(SimpleTestCase):

    def test_get(self):
        user = User()
        request = RequestFactory().get('/something?abc=def')
        request.user = user
        criteria = QueryDictCriteriaWithRequester.build(request)
        self.assertEqual(request.user, criteria.user)
        self.assertDictEqual(request.GET, criteria.raw)
        file_request = FileRequest(requester=user, criteria=criteria.marshall())
        criteria = QueryDictCriteriaWithRequester.restore_from(file_request)
        self.assertEqual(request.user, criteria.user)
        self.assertDictEqual(request.GET, criteria.raw)

    def test_post(self):
        user = User()
        request = RequestFactory().post('/something?abc=def')
        request.user = user
        criteria = QueryDictCriteriaWithRequester.build(request)
        self.assertEqual(request.user, criteria.user)
        self.assertDictEqual(request.POST, criteria.raw)
        file_request = FileRequest(requester=user, criteria=criteria.marshall())
        criteria = QueryDictCriteriaWithRequester.restore_from(file_request)
        self.assertEqual(request.user, criteria.user)
        self.assertDictEqual(request.POST, criteria.raw)

    def test_delete(self):
        request = RequestFactory().delete('/something?abc=def')
        request.user = User()
        self.assertRaises(RuntimeError, QueryDictCriteriaWithRequester.build, request)


class QueryDictCriteriaTest(SimpleTestCase):

    def test_get(self):
        request = RequestFactory().get('/something?abc=def')
        criteria = QueryDictCriteria.build(request)
        self.assertEqual(request.GET, criteria.raw)
        criteria = QueryDictCriteria.restore_from(FileRequest(criteria=criteria.marshall()))
        self.assertEqual(request.GET, criteria.raw)

    def test_post(self):
        request = RequestFactory().post('/something?abc=def')
        criteria = QueryDictCriteria.build(request)
        self.assertEqual(request.POST, criteria.raw)
        criteria = QueryDictCriteria.restore_from(FileRequest(criteria=criteria.marshall()))
        self.assertEqual(request.POST, criteria.raw)


class CriteriaTest(SimpleTestCase):

    def test_not_implemented(self):
        self.assertRaises(NotImplementedError, Criteria({}).marshall)
        self.assertRaises(NotImplementedError, Criteria.restore_from, FileRequest(criteria='abc'))
        self.assertRaises(NotImplementedError, Criteria.build, RequestFactory().get('/something?abc=def'))


class SimplePatternExtension(SimplePattern):

    def __init__(self, dataset):
        self.dataset = dataset

    def build_dataset(self, http_request):
        return self.dataset

    def respond_with_file(self, http_request, peek_data):
        return 'file'

    def respond_with_delay(self, http_request, peek_data):
        return 'delay'


class SimplePatternTest(SimpleTestCase):

    def test(self):
        request = object()
        delayed, response = SimplePatternExtension(Dataset('abc', [], True)).respond_to(request)
        self.assertTrue(delayed)
        self.assertEqual('delay', response)
        delayed, response = SimplePatternExtension(Dataset('abc', [], False)).respond_to(request)
        self.assertFalse(delayed)
        self.assertEqual('file', response)

    def test_not_implemented(self):
        request = object()
        self.assertRaises(NotImplementedError, SimplePattern().build_dataset, request)
        self.assertRaises(NotImplementedError, SimplePattern().respond_with_file, request, {})
        self.assertRaises(NotImplementedError, SimplePattern().respond_with_delay, request, {})
