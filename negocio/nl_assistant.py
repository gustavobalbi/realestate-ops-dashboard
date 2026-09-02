"""
Natural-language question assistant: text-to-SQL grounded in the real database.

Approach (documented per the brief's requirement that the technique be traceable to
real data, not a model hallucination):
  1. Gemini receives the schema (with notes about messy status casing) and produces a
     single read-only SELECT.
  2. The SELECT is validated (single statement, SELECT-only, no write/pragma keywords)
     and run against a *read-only* connection, independent of Django's own connection --
     SQLite opened with mode=ro locally, or a dedicated read-only SQL login on Azure SQL
     Database in production (see _run_readonly_query). If the engine rejects it (e.g. a
     column referenced on the wrong table), the real error message is fed back to Gemini
     to self-correct, up to MAX_TENTATIVAS_SQL attempts, before giving up and surfacing
     the error.
  3. The actual result rows are fed back to Gemini, which is instructed to answer using
     only those rows and to say so plainly if they don't answer the question.

The UI (negocio/templates/negocio/assistente.html) always shows the generated SQL and the
raw result table next to the answer, so the evaluator can verify the answer against the
data themselves rather than trust the prose alone.

Engine note: locally this runs against SQLite (django.db.backends.sqlite3); on Azure App
Service it runs against Azure SQL Database (ENGINE "mssql", see config/settings.py). Both
paths expose an identical noaccent(texto) SQL function to the model, so
_schema_description() and the prompts below barely need to branch by engine (just the
date-column note) -- the real per-engine work is in _run_readonly_query. On
SQL Server, noaccent() is a real T-SQL scalar function created once during setup (see
scripts/migrar_para_azure_sql.py), not a Python callback like SQLite's create_function.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import date

from django.conf import settings

from .normalize import strip_accents

MAX_ROWS = 200


def _usando_mssql() -> bool:
    return settings.DATABASES["default"]["ENGINE"] == "mssql"


def _schema_description() -> str:
    nota_data = (
        "As colunas de data são armazenadas como TEXT no formato 'YYYY-MM-DD'."
        if not _usando_mssql()
        else "As colunas de data são do tipo DATE nativo -- compare com literais "
        "'AAAA-MM-DD' diretamente (ex.: data_venda >= 'AAAA-01-01', com o ano correto para "
        "a pergunta) ou com YEAR(coluna)/MONTH(coluna), nunca fatiamento de string."
    )
    return f"""
Hoje é {date.today().isoformat()} (AAAA-MM-DD). Use essa data como referência para
qualquer expressão relativa na pergunta do usuário ("este ano", "no ano", "mês passado",
"último trimestre" etc.) -- nunca assuma um ano diferente do atual sem o usuário pedir
explicitamente por um ano específico.

Tabelas disponíveis. Todas as colunas de status/texto livre têm grafia inconsistente na
base real (ex.: "vendida", "Vendida", "VENDIDA" convivem). SEMPRE compare essas colunas
usando LOWER(TRIM(coluna)) e, quando fizer sentido, LIKE, nunca igualdade direta sensível
a caixa. {nota_data}

Está disponível a função SQL customizada noaccent(texto), que remove acentos e caixa
(retorna minúsculo sem acentuação). Use-a nos DOIS lados de qualquer comparação com nomes
próprios livres (cidade, nome de cliente/empreendimento, etc.), pois a pergunta do usuário
pode não usar a acentuação exata da base: ex. WHERE noaccent(cidade) = noaccent('Goiania')
ou WHERE noaccent(cidade) LIKE '%' || noaccent('sao paulo') || '%'.

empreendimentos(id, nome, cidade, uf, tipo, modelo_negocio, vgv_estimado, data_lancamento,
  status, observacoes)  -- um "empreendimento" é um projeto imobiliário completo (prédio,
  condomínio ou loteamento), dividido em várias "unidades" (os imóveis individuais à venda).
  - tipo: natureza do empreendimento -- Residencial / Comercial / Misto.
  - modelo_negocio: modelo de negócio jurídico/financeiro do empreendimento -- só existem 2
    categorias reais, "Obra por Administração" e "SPE Incorporadora" (SPE = Sociedade de
    Propósito Específico), mas a base tem grafia bem inconsistente para elas (ex.:
    "OBRA POR ADM", "obra por administracao", "incorporacao", "SPE incorporadora" convivem)
    -- sempre compare com noaccent(TRIM(modelo_negocio)) LIKE, nunca igualdade direta.
  - vgv_estimado: VGV = Valor Geral de Vendas, em reais (R$) -- a soma estimada do valor de
    venda de todas as unidades do empreendimento, o "tamanho" financeiro do projeto.
  - status: fase atual da obra em si -- Lançamento / Em obras / Concluído / Suspenso. Não
    confundir com o percentual mês a mês de obra_andamento.percentual_conclusao (mais
    granular) nem com unidades.status (esse é por unidade individual, vendida ou não).
unidades(id, empreendimento_id, identificador, tipo, area_privativa_m2, valor_tabela,
  status)  -- cada linha é um imóvel individual dentro de um empreendimento (um apartamento,
  uma sala etc.), o que de fato é vendido a um cliente.
  - tipo: Apartamento / Cobertura / Loja / Sala Comercial.
  - area_privativa_m2: área privativa em metros quadrados (m²).
  - valor_tabela: preço de tabela (de venda oficial, R$) daquela unidade -- pode ser
    diferente do valor_venda efetivamente pago (vendas.valor_venda), que reflete o negociado.
  - status: disponível / reservada / vendida / distrato (grafia bem variada: "vendida",
    "Vendida", "VENDIDA" etc. convivem) -- sempre LOWER(TRIM(status)). O valor bruto
    "Cancelado" (40 linhas) também existe na base, mas é a MESMA coisa que "Distrato" (uma
    venda que caiu e cuja unidade nunca voltou ao estoque) -- trate-o como "distrato" em
    qualquer filtro (ex.: WHERE LOWER(TRIM(status)) IN ('distrato','cancelado')). A regra de
    negócio atual da aplicação sempre devolve a unidade para "Disponível" quando um
    distrato é registrado, mas linhas históricas antigas da base podem não seguir isso.
clientes(id, nome, cidade, uf, perfil, data_cadastro, email)  -- cada linha é uma pessoa ou
  empresa que comprou (ou pode comprar) um imóvel. O e-mail é a chave real de identificação
  do cliente (nomes iguais podem ser pessoas diferentes -- homônimos, não duplicidade).
  - perfil: Morador (compra pra morar) / Investidor (compra pra alugar/revender) /
    Institucional (empresa/fundo comprando em nome próprio).
vendas(id, unidade_id, cliente_id, data_venda, valor_venda, forma_pagamento, status_venda,
  data_distrato)  -- cada linha é a venda de uma unidade a um cliente.
  - valor_venda: valor efetivamente vendido (R$), pode diferir do valor_tabela da unidade.
  - forma_pagamento: À vista / Financiamento / Parcelado Direto (direto com a incorporadora,
    sem banco).
  - status_venda: ativa/distrato (grafias variadas, incl. "Distratada" e "ATIVA"). Em 37
    linhas data_distrato está preenchida mas status_venda ainda diz "ativa" -- é um erro do
    sistema de origem. data_distrato é a fonte de verdade: uma venda só conta como "ativa"
    (em andamento, não cancelada) se LOWER(TRIM(status_venda)) começar com 'ativa' E
    data_distrato IS NULL. "Distrato" = a venda foi cancelada/desfeita depois de já ter sido
    fechada (diferente de uma unidade nunca ter sido vendida). Na direção oposta, 9 linhas
    têm status_venda = "distrato" mas data_distrato NULA -- aí o status já está certo, só
    falta a data (não conte como "ativa" nesse caso).
obra_andamento(id, empreendimento_id, mes_referencia, percentual_conclusao,
  custo_orcado_mes, custo_realizado_mes, observacoes)  -- acompanhamento físico-financeiro da
  OBRA, uma linha por empreendimento por mês: o quanto da construção estava pronta e quanto
  se gastou vs. o planejado naquele mês.
  - percentual_conclusao: % da obra fisicamente concluída até aquele mês (0 a 100). Não
    tem relação com empreendimentos.status nesta base (checado: a média de % é praticamente
    igual entre "Em obras"/"Concluído"/"Suspenso", e o único "Lançamento" aparece com 96,9%
    concluído) -- não assuma nem afirme que um diverge do outro.
  - custo_orcado_mes / custo_realizado_mes: custo de construção planejado vs. realmente
    gasto naquele mês (R$). "Risco/magnitude de estouro de custo" =
    SUM(custo_realizado_mes) - SUM(custo_orcado_mes) por empreendimento (positivo =
    estourou o orçamento). custo_orcado_mes (valor planejado) SÓ existe aqui, nunca em
    financeiro_mensal -- não junte as duas tabelas pra essa pergunta, cada uma responde uma
    pergunta diferente (uma é acompanhamento de obra, a outra é resultado contábil).
financeiro_mensal(id, empreendimento_id, mes_referencia, receita_reconhecida,
  custo_incorrido, despesas_corporativas_rat, resultado_reportado)  -- resultado financeiro
  CONTÁBIL mensal já fechado de cada empreendimento (não tem valor orçado/planejado, só o
  que já aconteceu). Todos os valores em reais (R$).
  - receita_reconhecida: receita contabilmente reconhecida no mês.
  - custo_incorrido: custo de construção já incorrido (mesmo número que
    obra_andamento.custo_realizado_mes, duplicado entre as duas tabelas).
  - despesas_corporativas_rat: despesas corporativas (administrativas, não ligadas
    diretamente à obra) rateadas para esse empreendimento naquele mês.
  - resultado_reportado: o lucro/prejuízo do mês como foi reportado/publicado.
  - "Resultado recalculado" = receita_reconhecida - custo_incorrido -
    despesas_corporativas_rat; uma linha é "inconsistente" quando esse valor recalculado
    difere do resultado_reportado (tolerância ~R$0,01) -- ou seja, o número publicado não
    bate com a conta simples a partir dos outros três campos.
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
    if _usando_mssql():
        return _run_readonly_query_mssql(sql)
    return _run_readonly_query_sqlite(sql)


def _run_readonly_query_sqlite(sql: str) -> tuple[list[str], list[tuple]]:
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


def _run_readonly_query_mssql(sql: str) -> tuple[list[str], list[tuple]]:
    """Conecta com um login SQL dedicado, só leitura (db_datareader), independente das
    credenciais de leitura/escrita que o Django usa -- mesma garantia de defesa em
    profundidade que o mode=ro do SQLite dá localmente: mesmo que a validação de SQL
    acima falhasse, esse login não teria permissão de escrever nada. Ver
    scripts/migrar_para_azure_sql.py para criar o login e o db_datareader."""
    import os

    import pyodbc

    db = settings.DATABASES["default"]
    usuario = os.environ.get("AZURE_SQL_READONLY_USER") or db["USER"]
    senha = os.environ.get("AZURE_SQL_READONLY_PASSWORD") or db["PASSWORD"]
    conn_str = (
        f"DRIVER={{ODBC Driver 18 for SQL Server}};"
        f"SERVER={db['HOST']},{db['PORT']};"
        f"DATABASE={db['NAME']};"
        f"UID={usuario};PWD={senha};"
        "Encrypt=yes;TrustServerCertificate=no;"
    )
    con = pyodbc.connect(conn_str, timeout=30)
    try:
        cur = con.cursor()
        cur.execute(sql)
        colunas = [d[0] for d in cur.description] if cur.description else []
        linhas = [tuple(row) for row in cur.fetchmany(MAX_ROWS)]
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


MAX_TENTATIVAS_SQL = 3  # 1 geração inicial + até 2 autocorreções guiadas pelo erro real do SQLite


def responder(pergunta: str) -> AssistantAnswer:
    client = _get_client()
    schema = _schema_description()

    sql_prompt = (
        f"{schema}\n\n"
        f"Pergunta do usuário: {pergunta}\n\n"
        "Gere APENAS uma consulta SQL SELECT (ou WITH ... SELECT) que responda a essa "
        "pergunta. Não use ponto e vírgula. Não explique nada, devolva só o SQL, em um "
        "bloco de código."
    )
    sql = _extract_sql(_generate(client, sql_prompt))
    _validate_sql(sql)

    # sqlite3.Error e pyodbc.Error não têm ancestral comum além de Exception -- import
    # lazy do pyodbc só quando de fato rodando contra o SQL Server (não instalado em dev
    # local, ver requirements.txt).
    if _usando_mssql():
        import pyodbc

        erros_sql: tuple[type[Exception], ...] = (pyodbc.Error,)
    else:
        erros_sql = (sqlite3.Error,)

    colunas: list[str] = []
    linhas: list[tuple] = []
    ultimo_erro: Exception | None = None
    for tentativa in range(MAX_TENTATIVAS_SQL):
        try:
            colunas, linhas = _run_readonly_query(sql)
            ultimo_erro = None
            break
        except erros_sql as exc:
            ultimo_erro = exc
            if tentativa == MAX_TENTATIVAS_SQL - 1:
                break
            correcao_prompt = (
                f"{schema}\n\n"
                f"Pergunta do usuário: {pergunta}\n\n"
                f"Você gerou esta consulta SQL:\n{sql}\n\n"
                f"Ela falhou ao executar no banco real com este erro:\n{exc}\n\n"
                "Gere uma nova consulta SQL SELECT (ou WITH ... SELECT) corrigida que "
                "responda à pergunta original, evitando esse erro -- preste atenção em qual "
                "tabela cada coluna realmente pertence antes de referenciá-la. Não use ponto "
                "e vírgula. Não explique nada, devolva só o SQL corrigido, em um bloco de "
                "código."
            )
            sql = _extract_sql(_generate(client, correcao_prompt))
            _validate_sql(sql)

    if ultimo_erro is not None:
        raise AssistantError(
            f"A consulta gerada falhou ao executar mesmo após correção automática: "
            f"{ultimo_erro}\nSQL: {sql}"
        ) from ultimo_erro

    answer_prompt = (
        "Você é um assistente de dados da Cambará Empreendimentos, escrevendo para um leitor "
        "leigo (ex.: um diretor ou gerente comercial) que não conhece nomes de coluna nem "
        "SQL -- use o dicionário de dados abaixo para traduzir tudo em termos de negócio "
        "(ex.: diga \"empreendimento\", \"valor de venda\", nunca \"vgv_estimado\" ou "
        "\"valor_venda\" literalmente). A consulta SQL foi gerada especificamente para "
        "responder à pergunta do usuário e já foi executada com sucesso no banco real -- "
        "confie no resultado dela como a resposta à pergunta (ex.: uma única linha com um "
        "COUNT(...) é a contagem pedida). Responda em português, de forma direta e objetiva, "
        "usando SOMENTE os dados retornados (não invente números). Se a tabela estiver "
        "vazia, diga isso claramente em vez de adivinhar.\n\n"
        "Formatação da resposta (obrigatória):\n"
        "- Texto corrido, em frases completas, como se estivesse falando com a pessoa -- "
        "sem markdown de nenhum tipo: nada de *, **, #, listas com \"-\" ou \"*\", nem "
        "blocos de código. Só texto puro (pode quebrar em parágrafos com linha em branco).\n"
        "- Todo valor monetário no padrão brasileiro, com prefixo R$, ponto como separador "
        "de milhar e vírgula com 2 casas decimais -- ex.: R$ 1.234.567,89 (nunca "
        "1234567.89, nunca R$1234567.89, nunca em notação científica).\n"
        "- Percentuais com vírgula decimal e símbolo % -- ex.: 72,5%.\n"
        "- Datas no formato dd/mm/aaaa.\n\n"
        f"{schema}\n\n"
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
