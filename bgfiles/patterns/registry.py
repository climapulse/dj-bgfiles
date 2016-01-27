# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from contextlib import contextmanager
from django.utils import translation, timezone


handlers = {}


def register(handler_class, file_types):
    """Register a handler for one or more file types.

    :param handler_class: a pattern implementation
    :param file_types: list of supported file types
    """
    for file_type in file_types:
        handlers[file_type] = handler_class


def dispatch(file_request_id):
    """Dispatches the handling of the file request.

    This will try to retrieve the file request and use its file type to retrieve a registered handler.
    That handler will then be asked to process the request.

    :param file_request_id: id of the file request
    :return: bool indicating whether there was actually something processed
    """
    from ..models import FileRequest
    request = FileRequest.objects.select_for_update().get(id=file_request_id)
    if request.finished_at:
        return False
    handler_class = handlers[request.file_type]
    translation_ctx = translation.override if request.requester_language else dummy
    timezone_ctx = timezone.override if request.requester_timezone else dummy
    with translation_ctx(request.requester_language):
        with timezone_ctx(request.requester_timezone):
            handler_class.handle(request)
    return True


@contextmanager
def dummy(s):
    yield s
