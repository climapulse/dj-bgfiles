# -*- coding: utf-8 -*-
"""
Tools for dealing with bgfiles functionality.

You could use the bgfiles models directly and build your own tooling around it, but this toolbox
should provide everything you need, safe for improved serving of files to the end user.

"""
from __future__ import unicode_literals, print_function, division, absolute_import
from datetime import timedelta
from django.conf import settings
from django.core.files import File
from django.core.serializers.json import DjangoJSONEncoder
from django.core.signing import dumps, loads, BadSignature
from django.http import HttpResponse, Http404
from django.utils import timezone, translation
import json
from .http import create_content_disposition
from .models import FileRequest


class JSONSerializer(object):
    """Custom serializer for tokens supporting UUIDs and the like."""

    def dumps(self, obj):
        return json.dumps(obj, separators=(',', ':'), cls=DjangoJSONEncoder).encode('latin-1')

    def loads(self, data):
        return json.loads(data.decode('latin-1'))


class Signer(object):
    """Default signer class, wraps ``django.core.signing`` functionality and settings.

    If you supply your own signer, you don't need to subclass this class, but you should provide compatible
    ``load`` and ``dump`` methods and a ``max_age`` property.

    """

    DEFAULT_SALT = 'bgfiles'
    DEFAULT_SERIALIZER = JSONSerializer

    def __init__(self, key=None, salt=DEFAULT_SALT, serializer=DEFAULT_SERIALIZER, compress=False, max_age=None):
        self.key = key
        self.salt = salt
        self.serializer = serializer
        self.compress = compress
        self.max_age = max_age

    def load(self, token):
        """Load the data from the token.

        This simply wraps ``django.core.signing.loads``. We don't wrap the exceptions raised by this function.

        :param token: token
        :type token: str
        :return: the data contained in the token
        """
        return loads(token, key=self.key, salt=self.salt, serializer=self.serializer, max_age=self.max_age)

    def dump(self, data):
        """Create a token with the data.

        This simply wraps ``django.core.signing.loads``. We don't wrap the exceptions raised by this function.

        :param data: data
        :type data: dict
        :return: the token
        """
        return dumps(data, key=self.key, salt=self.salt, serializer=self.serializer, compress=self.compress)


def get_default_signer():
    """Retrieve the configured default signer.

    Either we use the configured signer instance or we create our own instance of our default Signer. The parameters
    for that instance can be configured through your Django project settings.

    """
    signer = getattr(settings, 'BGFILES_DEFAULT_SIGNER', None)
    if not signer:
        key = getattr(settings, 'BGFILES_DEFAULT_KEY', settings.SECRET_KEY)
        salt = getattr(settings, 'BGFILES_DEFAULT_SALT', Signer.DEFAULT_SALT)
        serializer = getattr(settings, 'BGFILES_DEFAULT_SERIALIZER', Signer.DEFAULT_SERIALIZER)
        max_age = getattr(settings, 'BGFILES_DEFAULT_MAX_AGE', 86400)
        signer = Signer(key=key, salt=salt, serializer=serializer, max_age=max_age)
    return signer


def add_request(criteria='', file_type='', requester=None, content_type='', description='', language=None,
                tz=None):
    """Add a file request.

    :param criteria: the criteria that should be used to compose the file
    :type criteria: str
    :param file_type: the type of file to generate, e.g. "report-a" or "report-b"
    :type file_type: str
    :param requester: the instance of the user performing the requester
    :param content_type: the content or mime type of the resulting file
    :type content_type: str
    :param description: an optional description you can use to remind the user
    :type description: str
    :param language: the language to store; will be retrieved from ``django.utils.translation`` if None
    :type language: str
    :param tz: the timezone to store; will be retrieved from ``django.utils.timezone`` if None
    :type tz: str
    :return: the file request
    """
    if language is None:
        language = translation.get_language()
    if tz is None:
        tz = timezone.get_current_timezone_name()
    return FileRequest.objects.create(criteria=criteria, file_type=file_type, requester=requester,
                                      content_type=content_type, description=description, requested_at=timezone.now(),
                                      requester_language=language, requester_timezone=tz)


def attach_file(request, contents, filename=None, content_type=None, size=None):
    """Attach a file to a file request.

    This will mark the request as finished.

    :param request: the request
    :type request: bgfiles.models.FileRequest
    :param contents: the contents of the file/something that can be passed to a ``FileField``.
    :param filename: the filename; leave blank to maintain the current filename (if any)
    :type filename: str
    :param content_type: the content/mime type of the file; leave blank to maintain the current value (if any)
    :type content_type: str
    :param size: the size of the file in bytes; leave blank to maintain the current value (if any)
    :type size: int
    """
    request.attach_file(contents, filename, content_type, size=size)
    request.save()


def attach_local_file(request, filepath, filename=None, content_type=None, size=None):
    """Attach a local file to a file request.

    This will load the file and then pass it to ``attach_file``.

    :param request: the request
    :type request: bgfiles.models.FileRequest
    :param filepath: the full path to the file
    :type filepath: str
    :param filename: the filename; same as for ``attach_file``
    :type filename: str
    :param content_type: the content type; same as for ``attach_file``
    :type content_type: str
    :param size: the file size in bytes; same as for ``attach_file``
    :type size: int
    """
    with open(filepath, 'r') as contents:
        attach_file(request, File(contents), filename=filename, content_type=content_type, size=size)


def create_token(request, data=None, signer=None):
    """Create a requester-specific token for the request using the supplied signer.

    Creating a token this way requires the requester to be specified on the file request because their id
    will be included in the token. Otherwise a RuntimeError is raised.

    Note that the ``max_age`` property of the signer is used to set the expiration date of the file request.
    If you don't want to expire the request you should use a signer with no max age set.

    You can opt to add more data to the token and specify your own signer instance to use.

    :param request: file request
    :type request: bgfiles.models.FileRequest
    :param data: optional extra data to include in the token
    :type data: dict
    :param signer: signer to use; will default to the configured default signer
    :return: the token
    """
    if not request.requester_id:
        raise RuntimeError('Generating a requester token without a request is not possible')
    if not data:
        data = {}
    data['requester'] = request.requester_id
    return create_general_token(request, data, signer)


def create_general_token(request, data=None, signer=None):
    """Create a general token for the request using the supplied signer.

    In contrast with ``create_token`` this function does not require a requester to be set and won't embed
    their id even if a requester was specified in the request.

    Note that the ``max_age`` property of the signer is used to set the expiration date of the file request.
    If you don't want to expire the request you should use a signer with no max age set.

    You can opt to add more data to the token and specify your own signer instance to use.

    :param request: file request
    :type request: bgfiles.models.FileRequest
    :param data: optional extra data to include in the token
    :type data: dict
    :param signer: signer to use; will default to the configured default signer
    :return: the token
    """
    if not data:
        data = {}
    data['id'] = request.id
    signer = signer if signer else get_default_signer()
    token = signer.dump(data)
    if signer.max_age:
        request.expire_in(timedelta(seconds=signer.max_age))
        request.save()
    return token


def decode(token, require_requester=True, signer=None):
    """Decode a token.

    This turns the token back into the data you put in and returns a two-tuple containing the matching file
    request and that data. If the signer's ``max_age`` property is set this will also ensure the token isn't
    older than that max age (assuming you timestamp the token when you created it which is the default).

    If no matching file request is found, this will raise a ``FileRequest.DoesNotExist`` exception. When
    there's something wrong with the token the signer-specific exceptions will be raised. And if you require
    the requester id to be set but there's no such data in the token, this function will simply raise a
    ``BadSignature`` exception.

    :param token: token to decode
    :type token: str
    :param require_requester: whether we expect the requester id to be present in the data or not
    :type require_requester: bool
    :param signer: signer to use; defaults to the configured default signer
    :return: two-tuple (bgfiles.models.FileRequest, dict)
    """
    signer = signer if signer else get_default_signer()
    data = signer.load(token)
    filters = {'id': data['id']}
    if 'requester' in data:
        filters['requester_id'] = data['requester']
    elif require_requester:
        raise BadSignature()
    return FileRequest.objects.get(**filters), data


def serve(request, raise_on_missing=Http404, default_content_type='application/octet-stream'):
    """Serve the file attached to the request.

    Creates a simple HTTPResponse containing the attached file. When no file is attached, the ``raise_on_missing``
    exception will be raised, which defaults to ``Http404``. In case no content type was set on the file request,
    the ``default_content_type`` is used.

    :param request: the file request
    :type request: bgfiles.models.FileRequest
    :param raise_on_missing: exception to raise
    :type raise_on_missing: Exception
    :param default_content_type: content type to use when none was set on the file request
    :type default_content_type: str
    :return: an HTTP response
    """
    if not request.filehandle and raise_on_missing:
        raise raise_on_missing()
    content_type = request.content_type if request.content_type else default_content_type
    request.filehandle.open()
    try:
        response = HttpResponse(request.filehandle.file.read(), content_type=content_type)
    finally:
        request.filehandle.close()
    if request.filename:
        response['Content-Disposition'] = create_content_disposition(request.filename)
    return response
