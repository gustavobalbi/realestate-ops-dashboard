#!/bin/bash
# Comando de entrada do container (Azure Container Apps). Ao contrário do startup.sh do
# App Service, aqui não precisa instalar o driver ODBC -- ele já está na imagem (ver
# Dockerfile), então isto só roda o que precisa do banco/variáveis de ambiente reais.
set -e

python manage.py collectstatic --noinput
python manage.py migrate --noinput

exec gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 config.wsgi:application
