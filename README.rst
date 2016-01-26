=============================
dj-bgfiles
=============================

.. image:: https://badge.fury.io/py/dj-bgfiles.png
    :target: https://badge.fury.io/py/dj-bgfiles

.. image:: https://travis-ci.org/climapulse/dj-bgfiles.png?branch=master
    :target: https://travis-ci.org/climapulse/dj-bgfiles

Generate files in the background and allow users to pick them up afterwards using a token.

Documentation
-------------

The "full" documentation is at https://dj-bgfiles.readthedocs.org.

Quickstart
----------

First ensure you're using Django 1.8.4 or up. Next, install dj-bgfiles::

    pip install dj-bgfiles

Add it your ``INSTALLED_APPS`` and make sure to run the ``migrate`` command to create the necessary tables.


Features
--------

The most common use case is delivering sizeable data exports or complex reports to users without overloading the web
server, which is why ``bgfiles`` provides tools to:

- Store a file generation/download request
- Process that request later on, e.g. by using Celery or a cron job
- Send a notification to the requester including a secure link to download the file
- And serving the file to the requester (or others if applicable)

Example
-------

In our hypothetical project we want to provide users with the option to generate an xlsx file containing login events. Here's our model::

    class LoginEvent(models.Model):
        user = models.ForeignKey(User, blank=True, null=True)
        succeeded = models.BooleanField(default=True)
        created_at = models.DateTimeField(auto_now_add=True)

        def save(self, *args, **kwargs):
            self.succeeded = True if self.user_id else False
            super(LoginEvent, self).save(*args, **kwargs)

Our export allows a user to specify a timeframe through a form::

    class LoginExportFilterForm(models.Model):
        from_date = models.DateField()
        until_date = models.DateField(required=False)

        def apply_filters(self, queryset):
            """Apply the filters to our initial queryset."""
            data = self.cleaned_data
            queryset = queryset.filter(created_at__gte=data['from_date'])
            until_date = data.get('until_date')
            if until_date:
                queryset = queryset.filter(created_at__lte=until_date)
            return queryset

So our view would look like this initially::

    def export_login_events(request):
        if request.method == 'POST':
            form = LoginExportFilterForm(data=request.POST)
            if form.is_valid():
                # Grab our events
                events = LoginEvent.objects.all()
                # Apply the filters the user supplied
                events = form.apply_filters(events)
                # And write everything to an xlsx file and serve it as a HttpResponse
                return write_xlsx(events)
        else:
            form = LoginExportFilterForm()
        return render(request, 'reports/login_events_filter.html', context={'form': form})

But overnight, as it happens, our app got really popular so we have a ton of login events. We want to offload the
creation of large files to a background process that'll send a notification to the user when the file's ready with a
link to download it.

Enter ``bgfiles``.

Manually, using a Celery task
#############################

Here's how we could handle this manually using our ``toolbox`` and a Celery task::

    from bgfiles import toolbox

    def export_login_events(request):
        if request.method == 'POST':
            form = LoginExportFilterForm(data=request.POST)
            if form.is_valid():
                # Grab our events
                events = LoginEvent.objects.all()
                # Apply the filters the user supplied
                events = form.apply_filters(events)
                # We want to limit online file creation to at most 10000 events
                max_nr_events = 10000
                nr_events = events.count()
                if nr_events <= max_nr_events:
                    # Ok, deliver our file to the user
                    return write_xlsx(events)
                # The file would be too big. So let's grab our criteria
                criteria = request.POST.urlencode()
                # The content type is optional
                content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
                # Now add a file request
                with transaction.atomic():
                    file_request = toolbox.add_request(criteria, file_type='login_events',
                                                       requester=request.user, content_type=content_type)
                # Schedule a Celery task
                export_login_events_task.delay(file_request.id)
                # And let the user know we'll get back to them on that
                context = {'nr_events': nr_events, 'max_nr_events': max_nr_events}
                return render(request, 'reports/delayed_response.html', context=context)

        else:
            form = LoginExportFilterForm()
        return render(request, 'reports/login_events_filter.html', context={'form': form})

When we add a file request, we first marshall our criteria to something our database can store and we can easily
unmarshall later on. We specify a file type to support requests for different types of files and also record the
user that requested the file. The default ``bgfiles`` logic assumes only the user performing the request should be
able to download the file later on.

Anyway, our Celery task to create the file in the background might look like this::

    from bgfiles.models import FileRequest
    from django.http import QueryDict

    @task
    def export_login_events_task(file_request_id):
        # Grab our request. You might want to lock it or check if it's already been processed in the meanwhile.
        request = FileRequest.objects.get(id=file_request_id)
        # Restore our criteria
        criteria = QueryDict(request.criteria)
        # Build our form and apply the filters as specified by the criteria
        form = LoginExportFilterForm(data=criteria)
        events = LoginEvent.objects.all()
        events = form.apply_filters(events)
        # Write the events to an xlsx buffer (simplified)
        contents = write_xlsx(events)
        # Attach the contents to the request and add a filename
        toolbox.attach_file(request, contents, filename='login_events.xlsx'):
        # Generate a token for the requester of the file
        token = toolbox.create_token(request)
        # Grab the download url including our token
        download_url = reverse('mydownloads:serve', kwargs={'token': token})
        # And send out an email containing the link
        notifications.send_file_ready(request.requester, download_url, request.filename)

It should be pretty obvious what the above code is doing. Note that restoring our criteria is easy: we simply
instantiate a QueryDict. Yes, there's a bit of code duplication. We'll get to that later on.

Manually, using a cron job
##########################

Let's defer the generation to a cron job that will send out an email to our user. Our view would look the same, except
we won't schedule a Celery task. Our cron logic then might look like this::

    from bgfiles import toolbox
    from bgfiles.models import FileRequest
    from django.http import QueryDict

    def process_file_requests():
        # Only grab the requests that still need to be processed
        requests = FileRequest.objects.to_handle()
        # Process each one by delegating to a specific handler
        for request in requests:
            if request.file_type == 'login_events':
                process_login_events(request)
            elif request.file_type == 'something_else:
                process_something_else(request)
            else:
                raise Exception('Unsupported file type %s' % request.file_type)

    def process_login_events(request):
        # Restore our criteria
        criteria = QueryDict(request.criteria)
        # Build our form and apply the filters as specified by the criteria
        form = LoginExportFilterForm(data=criteria)
        events = LoginEvent.objects.all()
        events = form.apply_filters(events)
        # Write the events to an xlsx buffer (simplified)
        contents = write_xlsx(events)
        # Attach the contents to the request and add a filename
        toolbox.attach_file(request, contents, filename='login_events.xlsx'):
        # Generate a token for the requester of the file
        token = toolbox.create_token(request)
        # Get the download url
        download_url = reverse('mydownloads:serve', kwargs={'token': token})
        # Send out an email containing the link
        notifications.send_file_ready(request.requester, download_url, request.filename)

Add a management command to call ``process_file_requests``, drop it in crontab and you're good to go.

But wait! There's more!


Using the FullPattern
#####################

``bgfiles`` includes common patterns to structure your logic and minimize the code duplication. As you can see above
their usage is entirely optional.

In this example we'll use the ``bgfiles.patterns.FullPattern`` to render a template response when the file creation is
delayed and send out an email notification when the file is ready.

Here's our export handler class::

    class LoginEventExport(FullPattern):
        # These can all be overridden by get_* methods, e.g. get_file_type
        file_type = 'login_events'
        content_type = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        delayed_template_name = 'reports/delayed_response.html'
        email_subject = _('File %(filename)s is ready!')
        email_text_message = _('Come and get it: %(download_url)s')

        def get_items(self, criteria):
            # Our default criteria class provides the request's QueryDict (e.g. request.POST) as `raw` and the
            # requester as `user`. This method is used for both online and offline selection of the items we want to
            # use.
            form = LoginExportFilterForm(data=criteria.raw)
            if not form.is_valid():
                # If the form is invalid we raise an exception so our view knows about it and can show the errors.
                # If the form became invalid while we're offline... well, that shouldn't happen.
                raise InvalidForm(form=form)
            # Valid form: apply our filters and return our events
            return form.apply_filters(LoginEvent.objects.all())

        def evaluate_dataset(self, dataset, http_request):
            # When we've got our dataset, including our criteria and items, we need to evaluate whether we can
            # deliver it right now or need to delay it. Let's use our magic number.
            # Note that this is only called during an HTTP request.
            dataset.delay = dataset.items.count() > 10000

        def write_bytes(self, dataset, buffer):
            # This is where we write our dataset to the buffer. What goes on in here depends on your dataset, type of
            # file and so on.

Now let's adapt our view to use it::

    def export_login_events(request):
        if request.method == 'POST':
            try:
                delayed, response = LoginEventExport('login-events.xlsx').respond_to(request)
                return response
            except InvalidForm as exc:
                form = exc.form
        else:
            form = LoginExportFilterForm()
        return render(request, 'reports/login_events_filter.html', context={'form': form})

Here's what happening:

1. We let our export class handle the response when it's a POST request
2. It builds our dataset by wrapping the criteria (so we can use the same thing for both online and offline file generation) and fetching the items using ``get_items`` based on those criteria
3. It then lets you evaluate the dataset to decide on what to do next

If we don't delay the file creation, the pattern will write our bytes to a ``HttpResponse`` with the specified filename and content type.

But when we *do* delay the creation, it will:

1. Add a ``bgfiles.models.FileRequest`` to the database
2. Ask you to schedule the request using its ``schedule`` method
3. Respond with a template response using the ``delayed_template_name``

The ``schedule`` method does nothing by default, but if you use the included management command you can still have a cron
job process the outstanding requests automatically. If you prefer to use Celery, you can use the ``bgfiles.patterns.celery.ScheduleWithCeleryPattern``
class instead. It subclasses the ``FullPattern`` class.

This has our online part covered, but we still need to adapt our cron job. Here's what's left of it using the pattern::

    def process_login_events(request):
        LoginEventExport(request.filename).create_file(request)


That's it. The default implementation of ``create_file`` will:

1. Restore our criteria using the ``criteria_class`` specified on our exporter
2. Call ``get_items`` using those criteria
3. Call ``write_bytes`` to generate the file contents
4. Hook up the contents to our ``FileRequest`` and mark it as finished
5. Send out an email notification to the requester

But we can still improve. Read on!


Using the management command
############################

The included management command ``bgfiles`` allows you to clean up expired file requests, whether you use the included patterns or not::

    $ python manage.py bgfiles clean --timeout=60 --sleep=1

The above command will clean expired file requests, but will stop after a minute (or close enough) and go to sleep
for a second in between requests. By default it will also ignore file requests that have expired less than an
hour ago as to not interrupt any ongoing last-minute downloads. You can override this using the ``--leeway`` parameter.

You can also use the management command to process outstanding requests. To do this you'll need to register your
exporter in the registry::

    from bgfiles.patterns import FullPattern, registry

    class LoginEventExport(FullPattern):
        # Same as above


    # Register our class to process requests for our file type.
    # You might want to place this in your AppConfig.ready.
    registry.register(LoginEventExport, [LoginEventExport.file_type])


Now all that's needed to process file requests is to call the management command::

    $ python manage.py bgfiles process --sleep=1 --timeout=600 --items=20


This will process our outstanding requests by looking up the correct handler in the registry and calling the handler's ``handle``
classmethod which by default will restore a class instance (using the pattern's ``restore`` classmethod) and call its
``create_file`` method.


Serving the file
################

We've included a view you can use to serve the file. It will verify the token is valid, not expired and, by default,
check that the accessing user is also the user that requested the file. It doesn't provide any decent error messages
in case something is wrong, so you might want to wrap it with your own view::

    from bgfiles.views import serve_file, SuspiciousToken, SignatureHasExpired, UserIsNotRequester

    def serve(request, token):
        try:
            return serve_file(request, token, require_requester=True, verify_requester=True)
        except SuspiciousToken:
            # The token is invalid.
            # You could reraise this so Django can warn you about this suspicious operation
            return render(request, 'errors/naughty.html')
        except SignatureHasExpired:
            # Actually a subclass of PermissionDenied.
            # But you might want to inform the user they're a bit late to the party.
            return render(request, 'errors/signature_expired.html')
        except UserIsNotRequester:
            # Also a PermissionDenied subclass.
            # So the user's email was intercepted or they forwarded the mail to someone else.
            # Set verify_requester to False to disable this behavior.
            return render(request, 'errors/access_denied.html')


Allowing anyone to access a file
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

That is anyone with a valid token. By default ``bgfiles`` will assume you only want to serve a file to the user that
requested it. If you want to serve the file to anyone with a valid token it's just as easy.

Manually
~~~~~~~~

In our manual example we used ``toolbox.create_token`` to create our token. This embeds the id of the requester in the
token. To create a token anyone can use, use ``toolbox.create_general_token`` instead. Of course, the other token can
also be used by anyone because the verification is done in the view::

    # When we only want to serve the file to the requester, we use this:
    serve_file(request, token, require_requester=True, verify_requester=True)

    # When we want to serve the file to anyone, we use this:
    serve_file(request, token, require_requester=False, verify_requester=False)

Using patterns
~~~~~~~~~~~~~~
You can tell the pattern to use "general" tokens by setting the ``requester_only`` class variable to ``False`` or
by letting the ``is_requester_only`` method return ``False``. The changes to the view are the same as above.


Changing the signer
^^^^^^^^^^^^^^^^^^^

By default ``bgfiles`` uses Django's signing module to handle tokens. Configuring the signer can be done by changing settings:

- ``BGFILES_DEFAULT_KEY``: defaults to ``SECRET_KEY``
- ``BGFILES_DEFAULT_SALT``: defaults to ``bgfiles``. **We recommend specifying your own salt.**
- ``BGFILES_DEFAULT_SERIALIZER``: defaults to the ``JSONSerializer`` class included in the toolbox
- ``BGFILES_DEFAULT_MAX_AGE``: defaults to 86400 seconds (or a day)

If you need a custom default `Signer`, you can set ``BGFILES_DEFAULT_SIGNER`` to an instance of your signer class.

Of course, you should think about when to use the default signing method and settings and when to deviate and use a
custom one. Just be sure to use the same signer configuration when creating a token and when accepting a token::

    token = toolbox.create_token(request, signer=my_signer)

    # And in your view
    def serve(request, token):
        try:
            return serve_file(request, token, require_requester=True, verify_requester=True, signer=my_signer)
        except Stuff:
            # Error handling goes here

Specifying a custom signer on a pattern class::

    class MyExporter(FullPattern):
        signer = my_signer


Or::

    class MyExporter(FullPattern):

        def get_signer(self):
            return my_signer

