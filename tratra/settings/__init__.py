import os

env = os.environ.get('DJANGO_ENV')

if env == 'prod':
    from .prod import *
elif env == 'loadtest':
    from .loadtest import *  # tests de charge : base jetable, aucun SMS ni push (voir settings/loadtest.py)
else:
    from .dev import *
