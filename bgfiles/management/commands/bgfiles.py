# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import
from datetime import timedelta
from django.core.management import BaseCommand
from django.db import transaction
from django.utils import timezone
import time
from ...models import FileRequest
from ...patterns import registry


ACTION_PROCESS = 'process'
ACTION_CLEAN = 'clean'
DEFAULT_LEEWAY = 3600


class Command(BaseCommand):

    def add_arguments(self, parser):
        parser.add_argument('action', choices=[ACTION_PROCESS, ACTION_CLEAN],
                            help='Either process outstanding requests or clean expired requests. Note that processing '
                                 'requires the usage of the registry')
        parser.add_argument('--sleep', type=float,
                            help='Optional (floating point) sleep in seconds between handling requests')
        parser.add_argument('--timeout', type=int,
                            help='Maximum time to run in seconds; this is only an approximation.')
        parser.add_argument('--items', type=int, help='Maximum number of items to process')
        parser.add_argument('--leeway', type=int, help='Number of seconds leeway to allow for expired files. This '
                                                       'should prevent interrupting last-minute file downloads',
                            default=DEFAULT_LEEWAY)

    def handle(self, *args, **options):
        action = options['action']
        sleep = options.get('sleep')
        max_items = options.get('items')
        timeout = options.get('timeout')
        timeout = timeout + time.time() if timeout else None
        if action == ACTION_PROCESS:
            self.process(sleep, timeout, max_items)
        elif action == ACTION_CLEAN:
            self.clean(options['leeway'], sleep, timeout, max_items)
        else:
            raise RuntimeError('Unsupported action')

    def process(self, sleep, timeout, max_items):
        request_ids = FileRequest.objects.to_handle().values_list('id', flat=True)
        if max_items:
            request_ids = request_ids[:max_items]
        nr_items = 0
        for pk in request_ids:
            with transaction.atomic():
                generated = registry.dispatch(pk)
            if generated:
                nr_items += 1
                self.stdout.write('Handled request %s\n' % pk)
                if sleep:
                    time.sleep(sleep)
            else:
                self.stdout.write('Ignored request %s\n' % pk)
            if timeout and time.time() > timeout:
                self.stdout.write('Reached timeout. Stopping processing\n')
                break
        self.stdout.write('Handled %s requests' % nr_items)

    def clean(self, leeway, sleep, timeout, max_items):
        treshold = timezone.now()
        if leeway:
            treshold -= timedelta(seconds=leeway)
        with transaction.atomic():
            status, nr_deleted, total = FileRequest.objects.remove_expired(treshold, sleep, timeout, max_items)
        kwargs = {'status': status, 'nr_deleted': nr_deleted, 'total': total}
        if status == 'processed':
            self.stdout.write('Removed all {nr_deleted} expired files\n'.format(**kwargs))
        elif status == 'max_items':
            self.stdout.write('Stopped short because of max items: {nr_deleted}/{total}\n'.format(**kwargs))
        elif status == 'timeout':
            self.stdout.write('Stopped short because of timeout: {nr_deleted}/{total}\n'.format(**kwargs))
        else:
            self.stderr.write('Unknown exit status for cleaning: "{status}"\n'.format(**kwargs))
