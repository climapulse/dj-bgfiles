# -*- coding: utf-8 -*-
"""
Patterns providing shortcuts to schedule file request processing with Celery.

"""
from __future__ import unicode_literals, print_function, division, absolute_import
from .base import FullPattern


class ScheduleWithCeleryMixin(object):
    """Pattern mixin to schedule requests using Celery tasks."""

    # The task function to use
    task = None

    def schedule(self, file_request, http_request, dataset):
        """Implementation of the pattern's ``schedule`` method.

        :param file_request: the file request to schedule
        :param http_request: http request in case you need it
        :param dataset: the dataset in case you need it
        :return: the task result
        """
        params = [file_request, http_request, dataset]
        task = self.get_task(*params)
        return task.apply_async(**self.get_celery_kwargs(*params))

    def get_task(self, file_request, http_request, dataset):
        """Get the actual task function to call.

        Defaults to using the class ``task`` attribute.

        :param file_request: file request we want to schedule
        :param http_request: http request in case you need it
        :param dataset: the dataset in case you need it
        :return: the task function to use for scheduling
        """
        return self.task

    def get_task_args(self, file_request, http_request, dataset):
        """Get the args for the task; defaults to the id of the file request.

        :param file_request: file request to schedule
        :param http_request: http request in case you need it
        :param dataset: the dataset in case you need it
        :return: the args for the task
        """
        return [file_request.id]

    def get_task_kwargs(self, file_request, http_request, dataset):
        """Get the kwargs for the task.

        :param file_request: file request to schedule
        :param http_request: http request in case you need it
        :param dataset: the dataset in case you need it
        :return: the kwargs (dict) for the task
        """
        return {}

    def get_celery_kwargs(self, file_request, http_request, dataset):
        """Get the Celery kwargs for the task, passed to ``apply_async``.

        :param file_request: file request to schedule
        :param http_request: http request in case you need it
        :param dataset: the dataset in case you need it
        :return: the Celery options (dict) for the task
        """
        return {
            'args': self.get_task_args(file_request, http_request, dataset),
            'kwargs': self.get_task_kwargs(file_request, http_request, dataset)
        }


class ScheduleWithCeleryPattern(ScheduleWithCeleryMixin, FullPattern):
    """Final class using the Celery mixin and the FullPattern."""

    def evaluate_dataset(self, dataset, http_request):
        raise NotImplementedError()

    def write_bytes(self, dataset, output):
        raise NotImplementedError()

    def get_items(self, criteria):
        raise NotImplementedError()
