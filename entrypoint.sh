#!/bin/bash
# Comando de entrada do container. Não precisa instalar o driver ODBC em runtime -- ele já
# está na imagem (ver Dockerfile) -- então isto só roda o que precisa do banco/variáveis de
# ambiente reais. Usa a porta de $PORT quando definida (Render e a maioria dos PaaS
# injetam essa variável), com 8000 como padrão para rodar local via "docker run".
set -e

python manage.py collectstatic --noinput
python manage.py migrate --noinput

exec gunicorn --bind=0.0.0.0:${PORT:-8000} --timeout 600 --workers 2 config.wsgi:application
