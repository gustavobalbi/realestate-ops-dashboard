# Imagem de produção (Render, ou qualquer PaaS que builde a partir de um Dockerfile). O
# driver ODBC do SQL Server fica embutido na imagem -- não é usado no caminho padrão
# (SQLite, ver config/settings.py), mas fica pronto caso AZURE_SQL_SERVER seja definida no
# futuro, sem precisar reconstruir a imagem para instalar dependência nova.
# Fixado em "bookworm" (Debian 12) de propósito: "python:3.12-slim" simples aponta pra
# uma versão do Debian mais nova cujo verificador de assinatura (sqv) rejeita a chave
# SHA1 que o repositório da Microsoft ainda usa para o driver ODBC -- ver
# https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb abaixo,
# que é especificamente para bookworm.
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive

# unixodbc-dev + gcc/g++ são necessários para compilar o pyodbc (via pip, abaixo);
# curl/gnupg para adicionar o repositório da Microsoft e instalar o msodbcsql18. Ficam
# instalados na imagem final -- simplicidade > alguns MB de tamanho, aqui.
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl gnupg unixodbc-dev gcc g++ \
    && curl -sSL -O https://packages.microsoft.com/config/debian/12/packages-microsoft-prod.deb \
    && dpkg -i packages-microsoft-prod.deb \
    && rm -f packages-microsoft-prod.deb \
    && apt-get update \
    && ACCEPT_EULA=Y apt-get install -y --no-install-recommends msodbcsql18 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

ENTRYPOINT ["./entrypoint.sh"]
