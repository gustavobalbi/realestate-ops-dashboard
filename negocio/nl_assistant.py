"""
Natural-language question assistant: text-to-SQL grounded in the real database.

Approach (documented per the brief's requirement that the technique be traceable to
real data, not a model hallucination):
  1. Gemini receives the schema (with notes about messy status casing) and produces a
     single read-only SELECT.
  2. The SELECT is validated (single statement, SELECT-only, no write/pragma keywords)
     and run against a *read-only* SQLite connection (opened with mode=ro), independent
     of Django's connection.
  3. The actual result rows are fed back to Gemini, which is instructed to answer using
     only those rows and to say so plainly if they don't answer the question.

The UI (negocio/templates/negocio/assistente.html) always shows the generated SQL and the
raw result table next to the answer, so the evaluator can verify the answer against the
data themselves rather than trust the prose alone.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

from django.conf import settings

from .normalize import strip_accents

MAX_ROWS = 200

SCHEMA_DESCRIPTION = """
Tabelas disponíveis (SQLite). Todas as colunas de status/texto livre têm grafia
inconsistente na base real (ex.: "vendida", "Vendida", "VENDIDA" convivem). SEMPRE compare
essas colunas usando LOWER(TRIM(coluna)) e, quando fizer sentido, LIKE, nunca igualdade
direta sensível a caixa. As colunas de data são armazenadas como TEXT no formato
'YYYY-MM-DD'.

Está disponível a função SQL customizada noaccent(texto), que remove acentos e caixa
(retorna minúsculo sem acentuação). Use-a nos DOIS lados de qualquer comparação com nomes
próprios livres (cidade, nome de cliente/empreendimento, etc.), pois a pergunta do usuário
pode não usar a acentuação exata da base: ex. WHERE noaccent(cidade) = noaccent('Goiania')
ou WHERE noaccent(cidade) LIKE '%' || noaccent('sao paulo') || '%'.

empreendimentos(id, nome, cidade, uf, tipo, modelo_negocio, vgv_estimado, data_lancamento,
  status, observacoes)
unidades(id, empreendimento_id, identificador, tipo, area_privativa_m2, valor_tabela,
  status)  -- status: disponível/reservada/vendida/distrato/cancelado (grafias variadas)
clientes(id, nome, cidade, uf, perfil, data_cadastro, email)
vendas(id, unidade_id, cliente_id, data_venda, valor_venda, forma_pagamento, status_venda,
  data_distrato)  -- status_venda: ativa/distrato (grafias variadas, incl. "Distratada")
obra_andamento(id, empreendimento_id, mes_referencia, percentual_conclusao,
  custo_orcado_mes, custo_realizado_mes, observacoes)
financeiro_mensal(id, empreendimento_id, mes_referencia, receita_reconhecida,
  custo_incorrido, despesas_corporativas_rat, resultado_reportado)
usuarios(id, nome, email, papel, senha_hash)  -- nunca selecione senha_hash

Relacionamentos: unidades.empreendimento_id -> empreendimentos.id;
vendas.unidade_id -> unidades.id; vendas.cliente_id -> clientes.id;
obra_andamento.empreendimento_id / financeiro_mensal.empreendimento_id -> empreendimentos.id
""".strip()

FORBIDDEN_KEYWORDS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|ATTACH|DETACH|PRAGMA|REPLACE|CREATE|TRIGGER|"
    r"VACUUM|REINDEX|GRANT)\b",
    re.IGNORECASE,
)


class AssistantError(Exception):
    pass


@dataclass
class AssistantAnswer:
    pergunta: str
    sql: str
    colunas: list[str]
    linhas: list[tuple]
    resposta: str


def _get_client():
    if not settings.GEMINI_API_KEY:
        raise AssistantError(
            "GEMINI_API_KEY não configurada. Defina a variável de ambiente para usar o "
            "assistente (veja README)."
        )
    from google import genai

    return genai.Client(api_key=settings.GEMINI_API_KEY)


def _extract_sql(text: str) -> str:
    match = re.search(r"```\w*\s*\n?(.*?)```", text, re.DOTALL)
    sql = match.group(1) if match else text
    sql = sql.strip().strip(";").strip()
    return sql


def _validate_sql(sql: str) -> None:
    if not sql:
        raise AssistantError("O modelo não retornou nenhuma consulta SQL.")
    if ";" in sql:
        raise AssistantError("Apenas uma instrução SQL por consulta é permitida.")
    if not re.match(r"^\s*(SELECT|WITH)\b", sql, re.IGNORECASE):
        raise AssistantError("Apenas consultas de leitura (SELECT) são permitidas.")
    if FORBIDDEN_KEYWORDS.search(sql):
        raise AssistantError("A consulta gerada contém uma operação não permitida.")


def _run_readonly_query(sql: str) -> tuple[list[str], list[tuple]]:
    db_path = settings.DATABASES["default"]["NAME"]
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.create_function("noaccent", 1, lambda s: strip_accents(s).lower() if s is not None else None)
    try:
        cur = con.cursor()
        cur.execute(sql)
        colunas = [d[0] for d in cur.description] if cur.description else []
        linhas = cur.fetchmany(MAX_ROWS)
        return colunas, linhas
    finally:
        con.close()


def _generate(client, prompt: str) -> str:
    import time

    from google.genai import errors

    last_exc = None
    for attempt in range(3):
        try:
            resp = client.models.generate_content(model=settings.GEMINI_MODEL, contents=prompt)
            return resp.text or ""
        except errors.ServerError as exc:
            last_exc = exc
            time.sleep(1.5 * (attempt + 1))  # transient overload (503) -- brief backoff + retry
        except errors.APIError as exc:
            raise AssistantError(f"O provedor de IA (Gemini) recusou a requisição: {exc}") from exc
    raise AssistantError(
        f"O provedor de IA (Gemini) está indisponível no momento ({last_exc}). Tente novamente "
        "em instantes."
    ) from last_exc


def responder(pergunta: str) -> AssistantAnswer:
    client = _get_client()

    sql_prompt = (
        f"{SCHEMA_DESCRIPTION}\n\n"
        f"Pergunta do usuário: {pergunta}\n\n"
        "Gere APENAS uma consulta SQLite SELECT (ou WITH ... SELECT) que responda a essa "
        "pergunta. Não use ponto e vírgula. Não explique nada, devolva só o SQL, em um "
        "bloco de código."
    )
    sql = _extract_sql(_generate(client, sql_prompt))
    _validate_sql(sql)

    try:
        colunas, linhas = _run_readonly_query(sql)
    except sqlite3.Error as exc:
        raise AssistantError(f"A consulta gerada falhou ao executar: {exc}\nSQL: {sql}") from exc

    answer_prompt = (
        "Você é um assistente de dados da Cambará Empreendimentos. A consulta SQL abaixo foi "
        "gerada especificamente para responder à pergunta do usuário e já foi executada com "
        "sucesso no banco real -- confie no resultado dela como a resposta à pergunta (ex.: "
        "uma única linha com um COUNT(...) é a contagem pedida). Responda em português, de "
        "forma direta e objetiva, usando SOMENTE os dados retornados (não invente números). "
        "Se a tabela estiver vazia, diga isso claramente em vez de adivinhar.\n\n"
        f"Pergunta: {pergunta}\n\n"
        f"SQL executado: {sql}\n\n"
        f"Colunas do resultado: {colunas}\n"
        f"Linhas ({len(linhas)} de até {MAX_ROWS}): {linhas}\n"
    )
    resposta_texto = _generate(client, answer_prompt)

    return AssistantAnswer(
        pergunta=pergunta,
        sql=sql,
        colunas=colunas,
        linhas=linhas,
        resposta=resposta_texto.strip(),
    )
