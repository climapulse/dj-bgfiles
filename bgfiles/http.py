# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from django.utils.encoding import force_bytes, force_text
from django.utils.http import urlquote
import unicodedata


def create_content_disposition(filename, attachment=True):
    """Create the Content-Disposition HTTP header.

    This only supports ASCII and UTF-8 encoded strings. For UTF-8 encoded strings a fallback is added for
    older browsers.

    :param filename: filename to supply
    :type filename: str
    :param attachment: whether to force a dialog or not
    :type attachment: bool

    """
    # Start by replacing characters that might cause issues in some browsers
    cleaned = force_text(filename if filename else '')
    for ch in '/\\";':
        cleaned = cleaned.replace(ch, ' ')
    cleaned = force_bytes(cleaned)
    # Now try to guess the utf-8 and ascii variants of the filename
    utf8 = None
    ascii = attempt_decode(cleaned, 'ascii')
    # If ascii is set, we're dealing with a plain ascii string and no further processing is needed.
    if not ascii:
        utf8 = attempt_decode(cleaned, 'utf-8')
        if utf8:
            # So the filename is utf-8 encoded; now try to get a sane ascii version for older browsers
            try:
                ascii = unicodedata.normalize('NFKD', utf8).encode('ascii', 'ignore')
            except UnicodeDecodeError:
                pass
    # The string's not ascii nor utf-8. We can only hope for the best.
    if not ascii:
        ascii = cleaned
    ascii = force_text(ascii, encoding='ascii')
    format_params = {
        'serve_type': 'attachment' if attachment else 'inline',
        'ascii': ascii
    }
    if utf8 and ascii:
        format_params['utf8'] = urlquote(utf8)
        header_format = '{serve_type}; filename="{ascii}"; filename*=UTF-8\'\'{utf8}'
    else:
        header_format = '{serve_type}; filename="{ascii}"'
    return header_format.format(**format_params).encode('ascii')


def attempt_decode(s, encoding):
    try:
        return s.decode(encoding)
    except UnicodeDecodeError:
        return None
