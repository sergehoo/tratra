import os

env = os.environ.get('DJANGO_ENV')

if env == 'prod':
    from .prod import *
else:
    from .dev import *
