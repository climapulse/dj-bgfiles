# -*- coding: utf-8 -*-
from __future__ import unicode_literals, print_function, division, absolute_import

from django.core.files.base import ContentFile
from django.core.mail import send_mail
from django.http import HttpResponse, QueryDict
from django.shortcuts import render
from django.utils.encoding import force_text
from io import BytesIO
from .. import toolbox
from ..http import create_content_disposition


class InvalidCriteria(Exception):
    """Exception to indicate calling code of a pattern that the supplied criteria were invalid."""
    pass


class InvalidForm(InvalidCriteria):
    """Exception to raise when using a form to validate criteria.

    Pass the form as ``form=form`` to allow calling code to display errors.
    """

    def __init__(self, *args, **kwargs):
        form = kwargs.pop('form')
        super(InvalidCriteria, self).__init__(*args, **kwargs)
        self.form = form


class Criteria(object):
    """Wrapper for criteria, allowing marshalling and unmarshalling."""

    def __init__(self, raw):
        self.raw = raw

    def marshall(self):
        """Create a marshalled/serialized version of the criteria.

        This is used to store the criteria on a file request.
        """
        raise NotImplementedError()

    @classmethod
    def restore_from(cls, file_request):
        """Restore a Criteria instance from the file request.

        This is used to restore the criteria for our file generation when loading a file
        request from the database.
        """
        raise NotImplementedError()

    @classmethod
    def build(cls, http_request):
        """Useful method to simply build the initial criteria from an HTTP request.

        :param http_request: http request
        :return: Criteria instance
        """
        raise NotImplementedError()


class QueryDictCriteria(Criteria):
    """Criteria implementation assuming you want to use request.GET or request.POST as criteria.

    The ``raw`` attribute should be an instance of Django's ``QueryDict``.
    """

    def marshall(self):
        """Creates the URL encoded version of our QueryDict after sanitizing.

        :return: string
        """
        return self.sanitize(self.raw).urlencode()

    @classmethod
    def sanitize(cls, raw):
        # TODO Remove csrftoken
        return raw

    @classmethod
    def restore_from(cls, file_request):
        return cls(cls.criteria_query_dict(file_request))

    @classmethod
    def build(cls, http_request):
        return cls(cls.http_query_dict(http_request))

    @classmethod
    def criteria_query_dict(cls, file_request):
        """Create a QueryDict from the file request criteria (i.e. the original query string).

        :param file_request: the file request we want to restore the criteria from
        :return: QueryDict
        """
        return QueryDict(query_string=file_request.criteria)

    @classmethod
    def http_query_dict(cls, http_request):
        """Grab the correct query dict from the HTTP request.

        :param http_request: request
        :return: QueryDict
        """
        if http_request.method == 'POST':
            return http_request.POST
        if http_request.method == 'GET':
            return http_request.GET
        raise RuntimeError('Default implementation only supports GET and POST')


class QueryDictCriteriaWithRequester(QueryDictCriteria):
    """Extension of QueryDictCriteria that includes the requester.

    Note that the requester won't be serialized in the criteria since it's already available on the file
    request itself.
    """

    def __init__(self, raw, user):
        super(QueryDictCriteriaWithRequester, self).__init__(raw)
        self.user = user

    @classmethod
    def restore_from(cls, file_request):
        return cls(cls.criteria_query_dict(file_request), file_request.requester)

    @classmethod
    def build(cls, http_request):
        return cls(cls.http_query_dict(http_request), http_request.user)


class Dataset(object):
    """Wrapper for the dataset to use when creating the file.

    Contains the criteria instance, items and whether the processing should be delayed
    """

    def __init__(self, criteria, items=None, delay=False):
        self.criteria = criteria
        self.items = items
        self.delay = delay


class SimplePattern(object):
    """The most basic pattern.

    This simply lays out the basic scenario:

    - build the dataset for the current HTTP request
    - if the dataset indicates we need to delay processing, respond accordingly
    - otherwise respond with the file

    """

    def respond_to(self, http_request):
        """Respond to the file creation request.

        Returns a two-tuple (delayed, http response). The first value indicates whether processing was delayed,
        the second value (typically) contains the HTTP response.

        :param http_request: the HTTP request for the file
        :return: two-tuple
        """
        dataset = self.build_dataset(http_request)
        if not dataset.delay:
            return False, self.respond_with_file(http_request, dataset)
        return True, self.respond_with_delay(http_request, dataset)

    def build_dataset(self, http_request):
        """
        Build the dataset to use for this http request.

        :param http_request: the current http request
        :return: a dataset
        """
        raise NotImplementedError()

    def respond_with_file(self, http_request, dataset):
        """Create an HTTP response containing the file.

        :param http_request: the current http request
        :param dataset: the dataset we compiled, so you can re-use the work you've already done
        :return: HTTP response
        """
        raise NotImplementedError()

    def respond_with_delay(self, http_request, dataset):
        """Create a response when we've delayed the file creation.

        :param http_request: the current http request
        :param dataset: the dataset we compiled
        :return: HTTP response
        """
        raise NotImplementedError()


class WriterPattern(SimplePattern):
    """Pattern providing the logic for writing of the file, both online and offline.

    Your implementation should provide:

    - ``get_items``
    - ``evaluate_dataset``
    - ``write_bytes``

    Warning:

    - This pattern will not do a single thing when ``schedule`` is called. It assumes you use the information in
      the file request to process them with for example a cron job.
    - This pattern will not send out a notification. Implement ``send_notification`` to do so.
    - This pattern will not create an HTTP response when the processing is delayed. You'll have to implement
      ``create_delayed_response`` to do so or let your view handle it.

    See FullPattern for a pattern providing these options.

    """

    # The criteria class to use; defaults to QueryDictCriteriaWithRequester
    criteria_class = QueryDictCriteriaWithRequester
    # The file type to apply to the file request
    file_type = None
    # An optional description of the file to remind the user; stored when adding the file request
    file_description = None
    # The content type for the file
    content_type = None
    # The buffer class to supply to ``write_bytes``; defaults to io.BytesIO
    buffer_class = BytesIO
    # Whether we only want the requester to be able to download the file; defaults to True
    requester_only = True
    # The signer to use; defaults to the configured default signer
    signer = None
    # Whether to force the download of the file when we can create it online; defaults to True
    content_as_attachment = True

    def __init__(self, filename=None):
        self.filename = filename

    def build_dataset(self, http_request):
        """Build the dataset.

        This uses the configured criteria class to wrap the HTTP request, fetches the items using ``get_items``
        and then constructs a dataset to evaluate it with ``evaluate_dataset``.

        :param http_request: the current HTTP request
        :return: dataset
        """
        criteria = self.criteria_class.build(http_request)
        items = self.get_items(criteria)
        dataset = Dataset(criteria, items=items)
        self.evaluate_dataset(dataset, http_request)
        return dataset

    def respond_with_file(self, http_request, dataset):
        """Generate the file and return it as an HTTP response.

        This will simply call the ``write_bytes`` method to generate the file and wrap it in an HTTP response.

        :param http_request: the current HTTP request
        :param dataset: dataset we compiled
        :return: HTTP response
        """
        response = HttpResponse(content_type=self.content_type)
        response['Content-Disposition'] = create_content_disposition(self.get_filename(), self.content_as_attachment)
        bytebuffer = self.get_buffer_class()()
        self.write_bytes(dataset, bytebuffer)
        contents = bytebuffer.getvalue()
        bytebuffer.close()
        response.write(contents)
        return response

    def respond_with_delay(self, http_request, dataset):
        """Schedule a file request and respond to the user.

        This method will call the ``schedule`` method after adding the file request. So if you want custom
        scheduling, that's the place to be.

        :param http_request: the current HTTP request
        :param dataset: dataset we compiled
        :return: HTTP response (or something else)
        """
        file_request = toolbox.add_request(**self.get_file_request_data(http_request, dataset))
        schedule = self.schedule(file_request, http_request, dataset)
        return self.create_delayed_response(file_request, http_request, dataset, schedule)

    def get_items(self, criteria):
        """Retrieve the items we need to use to construct our file.

        Typically this is a queryset, but it might as well be a list, string or whatever you want. It can even
        be nothing at all. Here's an example assuming you're using a form to filter a queryset::

            form = IssueFilterForm(data=criteria.raw)
            issues = Issue.objects.all()
            return form.filter(issues)

        By default this pattern uses the ``QueryDictCriteriaWithRequester`` which means you can utilize the user
        as well::

            form = IssueFilterForm(data=criteria.raw)
            issues = Issue.objects.filter(assignee=criteria.user)
            return form.filter(issues)

        :param criteria: criteria instance defining which items to retrieve
        :return: the items
        """
        raise NotImplementedError()

    def evaluate_dataset(self, dataset, http_request):
        """Evaluate the dataset by setting its ``delay`` attribute.

        The dataset will contain the criteria and the items retrieved using ``get_items``.

        Your implementation might be simple or complex::

            # Simple
            dataset.delay = dataset.items.count > 500
            # Complex
            dataset.delay = CpuMonitor.get_current_load() > 0.25

        :param dataset: the dataset to evaluate
        :param http_request: the current HTTP request
        """
        raise NotImplementedError()

    def schedule(self, file_request, http_request, dataset):
        """Schedule the file request for processing.

        Does nothing by default, assuming you process outstanding requests manually/with a cron job.
        This is where you might schedule a Celery or RQ task for the file request.
        """
        return None

    def write_bytes(self, dataset, output):
        """Write the actual bytes for the file.

        Sorry, can't help you here. This is entirely up to you.

        :param dataset: the dataset containing the items and criteria
        :param output: output to write to; instance of ``get_buffer_class()``
        """
        raise NotImplementedError()

    def create_file(self, file_request):
        """Create the file offline based on the info in the file request.

        This method will:
        - Restore the criteria from the file request
        - Fetch the items using ``get_items``
        - Set up a buffer using ``get_buffer_class``
        - Call ``write_bytes``
        - Attach the corresponding file to the file request
        - Create a token (use ``is_requester_only`` to decide on whether the token is user-specific or general)
        - Pass the token and file request on to ``send_notification``

        :param file_request: request to process
        :return: result of sending out the notification to the user
        """
        criteria = self.criteria_class.restore_from(file_request)
        items = self.get_items(criteria)
        dataset = Dataset(criteria, items)
        bytebuffer = self.get_buffer_class()()
        self.write_bytes(dataset, bytebuffer)
        contents = bytebuffer.getvalue()
        bytebuffer.close()
        toolbox.attach_file(file_request, ContentFile(contents), self.get_filename(), self.get_content_type())
        token_data = self.get_token_data(file_request)
        if self.is_requester_only():
            token = toolbox.create_token(file_request, data=token_data, signer=self.get_signer())
        else:
            token = toolbox.create_general_token(file_request, data=token_data, signer=self.get_signer())
        return self.send_notification(file_request, token)

    def send_notification(self, file_request, token):
        """Send a notification to the user.

        By default this does absolutely nothing. Have a look at FullPattern for one that does something useful.

        :param file_request: the file request
        :param token: the token to access the file
        :return: the result of the notification (e.g. number of mails sent or Celery task)
        """
        return None

    def get_file_request_data(self, http_request, dataset):
        """Set up the data to use when adding a file request.

        :param http_request: the current HTTP request
        :param dataset: the dataset we compiled
        :return: dict
        """
        description = self.get_file_description()
        description = description if description else ''
        return {
            'criteria': dataset.criteria.marshall(),
            'file_type': self.get_file_type(),
            'description': description,
            'requester': http_request.user,
            'content_type': self.get_content_type()
        }

    def get_token_data(self, file_request):
        """Get optional additional data to embed in the token.

        :param file_request: the file request
        :return: dict
        """
        return {}

    def get_content_type(self):
        """Get the content type for the file.

        :return: by default returns the class-level ``content_type``
        """
        return self.content_type

    def get_file_type(self):
        """Get the type of file (e.g. 'report-a' or 'report-b').

        :return: by default returns the class-level ``file_type``
        """
        return self.file_type

    def get_file_description(self):
        """Get the description of the file (e.g. 'Your report A' or 'Your report B').

        :return: by default returns the class-level ``file_description``
        """
        return self.file_description

    def get_filename(self):
        """Get the name of the file (e.g. 'report-a.xlsx' or 'report-b.xlsx').

        :return: by default returns the ``filename`` attribute
        """
        return self.filename

    def is_requester_only(self):
        """Indicates whether we want the token to only be used by the requester of the file.

        :return: defaults to the class-level ``requester_only``.
        """
        return self.requester_only

    def get_buffer_class(self):
        """Get the buffer class to use when writing the bytes.

        :return: defaults to the class-level ``buffer_class``.
        """
        return self.buffer_class

    def get_signer(self):
        """Get the signer to use for our tokens.

        :return: defaults to the class-level ``signer`` or ``None`` (which means use the default one)
        """
        return self.signer if self.signer else None

    def create_delayed_response(self, file_request, http_request, dataset, schedule):
        """Create a response used when the processing is delayed.

        This is where you'd typically provide the user with an informative message to tell them you're working on
        it and you'll let them know when the file's ready.

        :param file_request: the file request we added
        :param http_request: the current HTTP request
        :param dataset: the dataset we compiled
        :param schedule: the result of calling ``schedule``
        :return: typically an HTTP response
        """
        return None

    @classmethod
    def restore(cls, file_request):
        """Restore an instance of this class from a file request.

        :param file_request: file request
        :return: class instance
        """
        return cls(file_request.filename)

    @classmethod
    def handle(cls, file_request):
        """Handle a file request.

        :param file_request: file request
        :return: result of sending out the notification after creating the file
        """
        instance = cls.restore(file_request)
        return instance.create_file(file_request)


class DelayedTemplateResponseMixin(object):
    """Pattern mixin providing a template response when the processing is delayed."""

    # Name of the template to use
    delayed_template_name = None

    def create_delayed_response(self, file_request, http_request, dataset, schedule):
        """Actually creates an HTTP response based on a template and optional context.

        :param file_request: the file request we added
        :param http_request: the current HTTP request
        :param dataset: the dataset we compiled
        :param schedule: the result of scheduling the processing of the HTTP request
        :return: an HTTP response
        """
        context = self.get_delayed_context_data(file_request=file_request, dataset=dataset, schedule=schedule)
        return render(http_request, self.get_delayed_template_name(), context=context)

    def get_delayed_template_name(self):
        """Get the template name to use.

        :return: defaults to the class-level ``delayed_template_name``
        """
        return self.delayed_template_name

    def get_delayed_context_data(self, **kwargs):
        """Hook to provide additional context data.

        :param kwargs: same parameters as ``create_delayed_response``
        :return: dict
        """
        return kwargs


class EmailNotificationMixin(object):
    """Pattern mixin to send out an email when a file is ready for download.

    Example::

        class IssueExport(EmailNotificationMixin, WriterPattern):
            email_subject = _('Your file %(filename)s is ready!')
            email_text_message = _('You can download it here: %(download_url)s')
            download_url = 'https://example.com/secure/%(token)s'

    """

    # Subject(-template) of the email; attributes of the file request and ``download_url`` will be inserted.
    email_subject = None
    # The from address
    from_email = None
    # Text(-template) of the email; attributes of the file request and ``download_url`` will be inserted.
    email_text_message = None
    # HTML(-template) of the email; attributes of the file request and ``download_url`` will be inserted.
    email_html_message = None
    # In case you've got a fixed download url; ``token`` will be inserted.
    download_url = None

    def send_notification(self, file_request, token):
        """Send out an email notification for the finished request.

        This will grab all the components of the email, insert the attributes of the file request and the
        download_url, and send it on its way.

        :param file_request: the file request
        :param token: the token to use
        :return: number of messages sent
        """
        template_kwargs = file_request.__dict__.copy()
        template_kwargs['download_url'] = self.get_download_url(file_request, token)
        subject = force_text(self.get_email_subject()) % template_kwargs
        message = force_text(self.get_email_text_message()) % template_kwargs
        html_message = force_text(self.get_email_html_message()) % template_kwargs
        recipients = self.get_email_recipients(file_request)
        return send_mail(subject, message, self.get_from_email(), recipients, html_message=html_message)

    def get_download_url(self, file_request, token):
        """Construct the download url for the request.

        By default uses the configured ``download_url`` and inserts the token.
        Don't forget to include your host.

        :param file_request: the file request
        :param token: the token to use
        :return: the download url
        """
        template_kwargs = file_request.__dict__.copy()
        template_kwargs['token'] = token
        return force_text(self.download_url) % template_kwargs

    def get_email_recipients(self, file_request):
        """Grab the recipients for the email.

        :param file_request: the file request
        :return: list of recipients; by default uses the requester of the file
        """
        return [file_request.requester.email]

    def get_email_subject(self):
        """Get the subject for the email.

        :return: defaults to the class-level ``email_subject``
        """
        return self.email_subject

    def get_email_text_message(self):
        """Get the text body for the email.

        :return: defaults to the class-level ``email_text_message``
        """
        return self.email_text_message

    def get_email_html_message(self):
        """Get the HTML body for the email.

        :return: defaults to the class-level ``email_html_message``
        """
        return self.email_html_message

    def get_from_email(self):
        """Get the from email address.

        :return: defaults to the class-level ``from_email``
        """
        return self.from_email


class FullPattern(DelayedTemplateResponseMixin, EmailNotificationMixin, WriterPattern):
    """Pattern class incorporating a delayed HTTP response and email notification.

    All that's left to do is implementing:
    - ``evaluate_dataset`` so we know whether to offload the file creation
    - ``write_bytes`` to actually have a file
    - ``get_items`` to select the items (if any) you need to create the file

    """

    def evaluate_dataset(self, dataset, http_request):
        raise NotImplementedError()

    def write_bytes(self, dataset, output):
        raise NotImplementedError()

    def get_items(self, criteria):
        raise NotImplementedError()
