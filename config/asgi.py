"""
Configuração ASGI do projeto config.

Expõe o callable ASGI como uma variável de nível de módulo chamada ``application``.

Mais informações sobre este arquivo em
https://docs.djangoproject.com/en/6.1/howto/deployment/asgi/
"""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

application = get_asgi_application()
