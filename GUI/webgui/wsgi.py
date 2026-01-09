# 06-06-25 By @FrancescoGrazioso -> "https://github.com/FrancescoGrazioso"


import os
from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "webgui.settings")
application = get_wsgi_application()