"""
Configuração WSGI do projeto config.

Expõe o callable WSGI como uma variável de nível de módulo chamada ``application``.

Mais informações sobre este arquivo em
https://docs.djangoproject.com/en/6.1/howto/deployment/wsgi/
"""

import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_wsgi_application()
