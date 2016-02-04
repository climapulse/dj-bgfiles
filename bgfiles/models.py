# -*- coding: utf-8 -*-
from __future__ import unicode_literals, absolute_import
from django.db import models
from django.conf import settings
from django.utils import timezone
from django.utils.encoding import python_2_unicode_compatible
from uuid import uuid4
import time
from .fields import ConfigurableFileField


class FileRequestManager(models.Manager):

    def to_handle(self):
        """Grab requests that still need to be handled.

        The requests are ordered by their date of requests, so older requests take precedence.

        :return: request queryset
        """
        return self.filter(finished_at__isnull=True).order_by('requested_at')

    def remove_expired(self, treshold, timeout=None, sleep=None, max_items=None):
        """Removes expired requests.

        It will return a three-tuple:

        - status: one of "processed", "max_items" or "timeout", depending on why the processing stopped
        - number of requests deleted
        - total number of requests that were available to delete

        :param treshold: requests should have expired before this
        :type treshold: datetime
        :param timeout: epoch time specifying when to stop processing
        :type timeout: int
        :param sleep: number of seconds to sleep in between requests
        :type sleep: float
        :param max_items: maximum number of items to remove
        :type max_items: int

        :return: (status, nr deleted, total items available to delete)
        """
        requests = self.filter(expires_at__lte=treshold)
        total = requests.count()
        nr_deleted = 0
        status = 'processed'
        for download in requests.order_by('expires_at').iterator():
            if sleep and nr_deleted > 0:
                time.sleep(sleep)
            # We process them manually to ensure the delete method is called, deleting any attached files as well.
            download.delete(using=self._db)
            nr_deleted += 1
            if max_items and nr_deleted == max_items:
                status = 'max_items'
                break
            if timeout and time.time() > timeout:
                status = 'timeout'
                break
        return status, nr_deleted, total


@python_2_unicode_compatible
class FileRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid4)
    criteria = models.TextField(blank=True)
    filehandle = ConfigurableFileField(blank=True, null=True)
    filename = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    file_type = models.CharField(max_length=100, blank=True, db_index=True)
    content_type = models.CharField(max_length=200, blank=True)
    size = models.BigIntegerField(blank=True, null=True)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, blank=True, null=True, related_name='requested_downloads',
                                  on_delete=models.CASCADE)
    requester_language = models.CharField(max_length=10, blank=True)
    requester_timezone = models.CharField(max_length=200, blank=True)
    requested_at = models.DateTimeField(db_index=True)
    finished_at = models.DateTimeField(blank=True, null=True, db_index=True)
    expires_at = models.DateTimeField(blank=True, null=True)
    objects = FileRequestManager()

    class Meta:
        ordering = ['-requested_at']

    def __str__(self):
        return '{} requested at {} by {}'.format(self.file_type, self.requested_at, self.requester)

    def delete(self, *args, **kwargs):
        # Ensure we remove our file
        if self.filehandle:
            self.filehandle.delete(save=False)
        return super(FileRequest, self).delete(*args, **kwargs)

    def attach_file(self, contents, filename=None, content_type=None, size=None, timestamp=None):
        timestamp = timestamp if timestamp else timezone.now()
        if filename:
            self.filename = filename
        if content_type:
            self.content_type = content_type
        if size:
            self.size = size
        self.filehandle.save(self.filename, contents)
        self.finished_at = timestamp

    def expire_in(self, delta, timestamp=None):
        timestamp = timestamp if timestamp else timezone.now()
        self.expires_at = timestamp + delta
