# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from django.conf import settings
from django.db.models import FileField


def get_storage():
    """Get the configured storage.

    :return: the configured storage or None, to force the use of Django's default storage
    """
    return getattr(settings, 'BG_FILES_STORAGE', None)


def get_upload_to():
    """Get the value for FileRequest's ``upload_to``.

    :return: the configured value or an empty string
    """
    return getattr(settings, 'BG_FILES_UPLOAD_TO', '')


class ConfigurableFileField(FileField):
    """Extension of Django's regular model FileField to prevent migration generation for every single change.

    Because the FileField will include the storage and upload_to attributes in the ``deconstruct``, this means
    any change to the relevant settings will cause Django to complain about missing migrations.

    If you want to have a copy of the old values for storage and upload_to in your migrations, please provide them
    yourself.

    """

    def __init__(self, *args, **kwargs):
        kwargs.setdefault('storage', get_storage())
        kwargs.setdefault('upload_to', get_upload_to())
        super(ConfigurableFileField, self).__init__(*args, **kwargs)

    def deconstruct(self):
        name, path, args, kwargs = super(ConfigurableFileField, self).deconstruct()
        kwargs.pop('storage', None)
        kwargs.pop('upload_to', None)
        return name, path, args, kwargs
