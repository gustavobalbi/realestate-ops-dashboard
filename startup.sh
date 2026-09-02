#!/bin/bash
# Startup command do Azure App Service (Linux, Python). Configurado no portal em
# Configuração > Geral > Comando de inicialização, ou via
# `az webapp config set --startup-file startup.sh`.
#
# A imagem do App Service não vem com o driver ODBC do SQL Server, e qualquer coisa
# instalada manualmente não persiste entre reinícios/redeploys -- por isso isso roda em
# TODO boot, não só na primeira vez. É rápido (poucos segundos com o cache do apt).
set -e

if ! odbcinst -q -d -n "ODBC Driver 18 for SQL Server" > /dev/null 2>&1; then
  echo "Instalando ODBC Driver 18 for SQL Server..."
  curl -sSL -O https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb
  dpkg -i packages-microsoft-prod.deb
  rm -f packages-microsoft-prod.deb
  apt-get update
  ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 unixodbc-dev
fi
# Ajuste o "debian/12" acima se o runtime Python do App Service estiver numa versão de
# Debian diferente -- confira com `cat /etc/debian_version` no console SSH do App Service.

python manage.py collectstatic --noinput
python manage.py migrate --noinput

gunicorn --bind=0.0.0.0:8000 --timeout 600 --workers 2 config.wsgi:application
