"""
Script único de migração: cria as 7 tabelas de negócio no Azure SQL Database (schema
equivalente ao da base SQLite fornecida, ver negocio/models.py) e copia todas as linhas
de data_cambara.sqlite3 para lá. Também cria a função dbo.noaccent (equivalente à função
Python registrada no SQLite por negocio/nl_assistant.py) e um login só-leitura
(db_datareader) dedicado ao assistente de IA.

Roda uma vez, manualmente, com as credenciais de administrador do banco -- não é chamado
pela aplicação em nenhum momento. Depois de rodar, "manage.py migrate" ainda precisa ser
executado (com as variáveis AZURE_SQL_* já definidas no ambiente) para criar as tabelas
internas do Django (django_session, django_migrations, django_content_type).

Uso:
    python scripts/migrar_para_azure_sql.py \
        --server meuservidor.database.windows.net \
        --database cambara \
        --admin-user meuadmin \
        --admin-password "..." \
        --readonly-password "..."

Requer pyodbc e o "ODBC Driver 18 for SQL Server" instalados localmente (mesmo driver
usado em produção -- ver requirements.txt e README).
"""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

import pyodbc

BASE_DIR = Path(__file__).resolve().parent.parent
SQLITE_PATH = BASE_DIR / "data_cambara.sqlite3"

# (nome da tabela, DDL das colunas, lista de colunas na ordem de leitura/inserção)
TABELAS = [
    (
        "empreendimentos",
        """
        id INT NOT NULL PRIMARY KEY,
        nome NVARCHAR(MAX) NOT NULL,
        cidade NVARCHAR(MAX) NOT NULL,
        uf NVARCHAR(MAX) NOT NULL,
        tipo NVARCHAR(MAX) NOT NULL,
        modelo_negocio NVARCHAR(MAX) NOT NULL,
        vgv_estimado FLOAT NULL,
        data_lancamento DATE NOT NULL,
        status NVARCHAR(MAX) NOT NULL,
        observacoes NVARCHAR(MAX) NULL
        """,
        ["id", "nome", "cidade", "uf", "tipo", "modelo_negocio", "vgv_estimado",
         "data_lancamento", "status", "observacoes"],
    ),
    (
        "unidades",
        """
        id INT NOT NULL PRIMARY KEY,
        empreendimento_id INT NOT NULL,
        identificador NVARCHAR(MAX) NOT NULL,
        tipo NVARCHAR(MAX) NOT NULL,
        area_privativa_m2 FLOAT NOT NULL,
        valor_tabela FLOAT NOT NULL,
        status NVARCHAR(MAX) NOT NULL
        """,
        ["id", "empreendimento_id", "identificador", "tipo", "area_privativa_m2",
         "valor_tabela", "status"],
    ),
    (
        "clientes",
        """
        id INT NOT NULL PRIMARY KEY,
        nome NVARCHAR(MAX) NOT NULL,
        cidade NVARCHAR(MAX) NULL,
        uf NVARCHAR(MAX) NULL,
        perfil NVARCHAR(MAX) NULL,
        data_cadastro DATE NOT NULL,
        email NVARCHAR(MAX) NULL
        """,
        ["id", "nome", "cidade", "uf", "perfil", "data_cadastro", "email"],
    ),
    (
        "vendas",
        """
        id INT NOT NULL PRIMARY KEY,
        unidade_id INT NOT NULL,
        cliente_id INT NOT NULL,
        data_venda DATE NOT NULL,
        valor_venda FLOAT NOT NULL,
        forma_pagamento NVARCHAR(MAX) NOT NULL,
        status_venda NVARCHAR(MAX) NOT NULL,
        data_distrato DATE NULL
        """,
        ["id", "unidade_id", "cliente_id", "data_venda", "valor_venda", "forma_pagamento",
         "status_venda", "data_distrato"],
    ),
    (
        "obra_andamento",
        """
        id INT NOT NULL PRIMARY KEY,
        empreendimento_id INT NOT NULL,
        mes_referencia DATE NOT NULL,
        percentual_conclusao FLOAT NOT NULL,
        custo_orcado_mes FLOAT NOT NULL,
        custo_realizado_mes FLOAT NOT NULL,
        observacoes NVARCHAR(MAX) NULL
        """,
        ["id", "empreendimento_id", "mes_referencia", "percentual_conclusao",
         "custo_orcado_mes", "custo_realizado_mes", "observacoes"],
    ),
    (
        "financeiro_mensal",
        """
        id INT NOT NULL PRIMARY KEY,
        empreendimento_id INT NOT NULL,
        mes_referencia DATE NOT NULL,
        receita_reconhecida FLOAT NOT NULL,
        custo_incorrido FLOAT NOT NULL,
        despesas_corporativas_rat FLOAT NOT NULL,
        resultado_reportado FLOAT NOT NULL
        """,
        ["id", "empreendimento_id", "mes_referencia", "receita_reconhecida",
         "custo_incorrido", "despesas_corporativas_rat", "resultado_reportado"],
    ),
    (
        "usuarios",
        """
        id INT NOT NULL PRIMARY KEY,
        nome NVARCHAR(MAX) NOT NULL,
        email NVARCHAR(MAX) NOT NULL,
        papel NVARCHAR(MAX) NOT NULL,
        senha_hash NVARCHAR(MAX) NOT NULL
        """,
        ["id", "nome", "email", "papel", "senha_hash"],
    ),
]

INDICES_FK = [
    ("unidades", "empreendimento_id"),
    ("vendas", "unidade_id"),
    ("vendas", "cliente_id"),
    ("obra_andamento", "empreendimento_id"),
    ("financeiro_mensal", "empreendimento_id"),
]

# Equivalente T-SQL de negocio.normalize.strip_accents(x).lower() -- Azure SQL Database
# não suporta CLR, então em vez de uma função Python registrada (como no SQLite) isto é
# uma cadeia de REPLACE explícita para os acentos que aparecem nesta base.
SQL_NOACCENT_FUNCTION = """
CREATE FUNCTION dbo.noaccent (@texto NVARCHAR(MAX))
RETURNS NVARCHAR(MAX)
AS
BEGIN
    IF @texto IS NULL RETURN NULL;
    DECLARE @s NVARCHAR(MAX) = LOWER(LTRIM(RTRIM(@texto)));
    SET @s = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(@s, N'á', 'a'), N'à', 'a'), N'â', 'a'), N'ã', 'a'), N'ä', 'a');
    SET @s = REPLACE(REPLACE(REPLACE(REPLACE(@s, N'é', 'e'), N'è', 'e'), N'ê', 'e'), N'ë', 'e');
    SET @s = REPLACE(REPLACE(REPLACE(REPLACE(@s, N'í', 'i'), N'ì', 'i'), N'î', 'i'), N'ï', 'i');
    SET @s = REPLACE(REPLACE(REPLACE(REPLACE(REPLACE(@s, N'ó', 'o'), N'ò', 'o'), N'ô', 'o'), N'õ', 'o'), N'ö', 'o');
    SET @s = REPLACE(REPLACE(REPLACE(REPLACE(@s, N'ú', 'u'), N'ù', 'u'), N'û', 'u'), N'ü', 'u');
    SET @s = REPLACE(@s, N'ç', 'c');
    RETURN @s;
END
"""


def parse_args():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--server", required=True, help="ex.: meuservidor.database.windows.net")
    p.add_argument("--database", required=True)
    p.add_argument("--port", default="1433")
    p.add_argument("--admin-user", required=True)
    p.add_argument("--admin-password", required=True)
    p.add_argument("--readonly-user", default="assistente_ia")
    p.add_argument("--readonly-password", required=True)
    return p.parse_args()


def conectar(args) -> pyodbc.Connection:
    conn_str = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={args.server},{args.port};DATABASE={args.database};"
        f"UID={args.admin_user};PWD={args.admin_password};"
        "Encrypt=yes;TrustServerCertificate=no;"
    )
    return pyodbc.connect(conn_str, timeout=30, autocommit=False)


def criar_tabelas(cur) -> None:
    for nome, ddl_colunas, _colunas in TABELAS:
        cur.execute(
            f"IF OBJECT_ID('dbo.{nome}', 'U') IS NOT NULL DROP TABLE dbo.{nome};"
        )
        cur.execute(f"CREATE TABLE dbo.{nome} ({ddl_colunas});")
        print(f"  tabela {nome} criada")
    for tabela, coluna in INDICES_FK:
        cur.execute(
            f"CREATE INDEX ix_{tabela}_{coluna} ON dbo.{tabela} ({coluna});"
        )
    print("  índices de chave estrangeira criados")


def copiar_dados(cur_sqlite, cur_mssql) -> None:
    for nome, _ddl, colunas in TABELAS:
        cur_sqlite.execute(f"SELECT {', '.join(colunas)} FROM {nome}")
        linhas = cur_sqlite.fetchall()
        placeholders = ", ".join("?" for _ in colunas)
        insert_sql = f"INSERT INTO dbo.{nome} ({', '.join(colunas)}) VALUES ({placeholders})"
        cur_mssql.fast_executemany = True
        cur_mssql.executemany(insert_sql, linhas)
        print(f"  {len(linhas)} linha(s) copiadas para {nome}")


def criar_funcao_noaccent(cur) -> None:
    cur.execute("IF OBJECT_ID('dbo.noaccent', 'FN') IS NOT NULL DROP FUNCTION dbo.noaccent;")
    cur.execute(SQL_NOACCENT_FUNCTION)
    print("  função dbo.noaccent criada")


def criar_login_readonly(cur, args) -> None:
    cur.execute(
        "IF NOT EXISTS (SELECT * FROM sys.database_principals WHERE name = ?) "
        "BEGIN "
        f"  CREATE USER [{args.readonly_user}] WITH PASSWORD = '{args.readonly_password}'; "
        "END",
        args.readonly_user,
    )
    cur.execute(f"ALTER ROLE db_datareader ADD MEMBER [{args.readonly_user}];")
    print(f"  usuário {args.readonly_user} criado/atualizado com db_datareader")


def main():
    args = parse_args()

    print(f"Lendo {SQLITE_PATH} ...")
    con_sqlite = sqlite3.connect(str(SQLITE_PATH))
    cur_sqlite = con_sqlite.cursor()

    print(f"Conectando em {args.server} ...")
    con_mssql = conectar(args)
    cur_mssql = con_mssql.cursor()

    try:
        print("Criando tabelas...")
        criar_tabelas(cur_mssql)
        con_mssql.commit()

        print("Copiando dados...")
        copiar_dados(cur_sqlite, cur_mssql)
        con_mssql.commit()

        print("Criando função noaccent...")
        criar_funcao_noaccent(cur_mssql)
        con_mssql.commit()

        print("Criando login somente-leitura para o assistente de IA...")
        criar_login_readonly(cur_mssql, args)
        con_mssql.commit()

        print("\nConcluído. Ainda falta rodar 'manage.py migrate' com as variáveis "
              "AZURE_SQL_* definidas, para criar as tabelas internas do Django.")
    except Exception:
        con_mssql.rollback()
        raise
    finally:
        con_sqlite.close()
        con_mssql.close()


if __name__ == "__main__":
    main()
