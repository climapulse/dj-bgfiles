# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from django.core.exceptions import PermissionDenied, SuspiciousOperation
from django.core.signing import BadSignature, SignatureExpired
from django.http import Http404
from django.utils import six
import sys
from . import toolbox
from .models import FileRequest


class SuspiciousToken(SuspiciousOperation):
    """Exception to raise when the token is simply invalid.

    It subclasses SuspiciousOperation to take advantage of Django's reporting functionality,
    because An invalid token means either (a) the developer made a crucial mistake or (b) someone's
    trying to poke holes.

    """
    pass


class SignatureHasExpired(PermissionDenied):
    """Exception to raise when the signature was valid but has expired."""
    pass


class UserIsNotRequester(PermissionDenied):
    """Exception to raise when the current user is not the requester."""
    pass


def evaluate_request(request, token, require_requester=True, verify_requester=True, signer=None):
    """Utility method to evaluate a request before serving the file.

    This allows you to for example show a preview page to the user before serving the file.

    Note that the exception handling assumes you're using a Signer based on django.core.signing. It will turn:

    - a ``FileRequest.DoesNotExist`` into Django's `Http404` exception
    - a ``SignatureExpired`` into ``SignatureHasExpired``
    - a ``BadSignature`` into ``SuspiciousToken``

    If ``verify_requester`` is set to ``True`` (the default) and the current user does not match the requester, a
    ``UserIsNotRequester`` exception will be raised.

    :param request: the request
    :type request: django.http.request.HttpRequest
    :param token: the token
    :type token: str
    :param require_requester: whether we expect the token to contain the request
    :type require_requester: bool
    :param verify_requester: whether we need to verify the current user is the requester
    :type verify_requester: bool
    :param signer: signer to use
    :return: two-tuple containing the file request and the data in the token
    """
    file_request, data = None, None
    try:
        file_request, data = toolbox.decode(token, require_requester=require_requester, signer=signer)
    except FileRequest.DoesNotExist:
        raise Http404()
    except SignatureExpired as e:
        six.reraise(SignatureHasExpired, SignatureHasExpired(e), sys.exc_info()[2])
    except BadSignature as e:
        six.reraise(SuspiciousToken, SuspiciousToken(e), sys.exc_info()[2])
    if verify_requester and file_request.requester != request.user:
        raise UserIsNotRequester()
    return file_request, data


def serve_file(request, token, require_requester=True, verify_requester=True, signer=None):
    """Basic view to serve a file.

    Uses ``evaluate_request`` under the hood. Please refer to that function to view information about exceptions.

    :param request: the file request
    :type request: bgfiles.models.FileRequest
    :param token: the token
    :type token: str
    :param require_requester: whether we expect the token to contain the request
    :type require_requester: bool
    :param verify_requester: whether we need to verify the current user is the requester
    :type verify_requester: bool
    :param signer: signer to use
    :return: django.http.HTTPResponse

    """
    file_request, data = evaluate_request(request, token, require_requester=require_requester,
                                          verify_requester=verify_requester, signer=signer)
    return toolbox.serve(file_request)
