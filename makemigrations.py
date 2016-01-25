import sys

from django.core.management import call_command

try:
    from django.conf import settings
    from django.test.utils import get_runner

    settings.configure(
        DEBUG=True,
        USE_TZ=True,
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
            }
        },
        ROOT_URLCONF="bgfiles.urls",
        INSTALLED_APPS=[
            "django.contrib.auth",
            "django.contrib.contenttypes",
            "bgfiles",
        ],
        SITE_ID=1,
        MIDDLEWARE_CLASSES=(),
    )

    try:
        import django
        setup = django.setup
    except AttributeError:
        pass
    else:
        setup()

except ImportError:
    import traceback
    traceback.print_exc()
    raise ImportError("To fix this error, run: pip install -r requirements-test.txt")


def make_migrations(*args):
    if not args:
        args = ['bgfiles']
    call_command('makemigrations', *args)


if __name__ == '__main__':
    make_migrations(*sys.argv[1:])
