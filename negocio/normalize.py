"""
Canonicalization rules for the messy free-text fields in the base.

The source data mixes casing and spelling for the same underlying concept
(e.g. unit status appears as "vendida", "Vendida", "VENDIDA"). Historical rows are never
rewritten in place -- callers normalize at read time using the helpers below, and new
rows written by this app (negocio/services.py) always use the canonical spelling.

STATUS_UNIDADE canon: disponivel | reservada | vendida | distrato
STATUS_VENDA canon:   ativa | distrato

Finding (aplicado): toda unidade com status bruto "cancelado" tem uma venda vinculada com
status canônico "distrato" (verificado contra as 40 linhas da base -- correspondência de
100%), ou seja, "cancelado" e "distrato" são duas grafias históricas diferentes para o
mesmo evento: uma venda que caiu e cuja unidade nunca voltou ao estoque disponível no
cadastro. Diferente das outras grafias inconsistentes deste módulo (que só variam
maiúscula/acento), aqui a diferença é conceitual, não ortográfica -- por isso
norm_status_unidade() funde os dois no mesmo bucket canônico "distrato" (não existe mais
um bucket "cancelado" separado). Isso aparece na tela Dados: uma unidade que vinha da base
como "Cancelado" é exibida e filtrável como "DISTRATO", igual a qualquer outra. Vai
"para frente" (novas escritas) a app já seguia a regra do briefing de qualquer forma: todo
novo distrato devolve a unidade para "disponivel".

Finding: 37 das linhas de vendas com data_distrato preenchida ainda têm status_venda
dizendo "ativa" (em alguma grafia) -- o sistema de origem falhou em atualizar esse campo
ao registrar o distrato. data_distrato é tratado como autoritativo: qualquer linha com
data de distrato preenchida conta como distrato independente do que status_venda diga (ver
venda_esta_ativa abaixo). Diferente das outras colunas de status deste módulo (que só
canonicalizam a GRAFIA do texto bruto), a coluna STATUS de vendas na tela Dados mostra o
resultado de venda_esta_ativa(), não o texto bruto -- nessas 37 linhas ela já aparece como
"DISTRATO" mesmo com status_venda dizendo "Ativa" (ver negocio/data_browser.py:
_status_venda). Não existem duas colunas de status lado a lado -- só uma, já corrigida.

Finding: na direção oposta, 9 linhas de vendas têm status_venda canonicamente "distrato"
mas data_distrato NULA -- o sistema de origem não registrou quando o distrato aconteceu.
Diferente do achado anterior, aqui o status já está certo (venda_esta_ativa() retorna
False de qualquer forma, com ou sem data) -- o problema não é o status estar errado, é a
data estar faltando. A tela Dados marca isso explicitamente na coluna DATA DE DISTRATO com
"SEM REGISTRO" em vez do "--" genérico (que nessa coluna, no resto da base, sempre
significa "venda ainda ativa").
"""

import datetime as dt
import unicodedata

CANONICAL_UNIDADE = {
    "disponivel": "Disponível",
    "reservada": "Reservada",
    "vendida": "Vendida",
    "distrato": "Distrato",
}

CANONICAL_VENDA = {
    "ativa": "Ativa",
    "distrato": "Distrato",
}

CANONICAL_MODELO_NEGOCIO = {
    "obra_administracao": "Obra por Administração",
    "spe_incorporadora": "SPE Incorporadora",
}

# Statuses (já normalizados) que tornam uma unidade inelegível para uma nova venda.
UNIDADE_INDISPONIVEL = {"reservada", "vendida", "distrato"}


def strip_accents(value: str) -> str:
    return "".join(
        ch for ch in unicodedata.normalize("NFKD", value) if not unicodedata.combining(ch)
    )


def norm_key(value: str | None) -> str:
    """Lowercase, trimmed, accent-free key used to bucket free-text values."""
    if value is None:
        return ""
    return strip_accents(value).strip().lower()


def norm_status_unidade(value: str | None) -> str:
    """Return the canonical bucket key (e.g. 'vendida') for a raw unidades.status value.

    "cancelado" funde no bucket "distrato" -- ver o "Finding (aplicado)" no docstring do
    módulo: são o mesmo evento de negócio, não duas grafias do mesmo texto."""
    key = norm_key(value)
    if key in ("vendida",):
        return "vendida"
    if key in ("distrato", "cancelado"):
        return "distrato"
    if key in ("reservada",):
        return "reservada"
    if key in ("disponivel", "disponível"):
        return "disponivel"
    return key


def norm_status_venda(value: str | None) -> str:
    key = norm_key(value)
    if key in ("distrato", "distratada"):
        return "distrato"
    if key in ("ativa",):
        return "ativa"
    return key


def venda_esta_ativa(status_venda: str | None, data_distrato: dt.date | None) -> bool:
    """True if a sale should be counted as active.

    data_distrato is authoritative over status_venda: a filled-in distrato date always
    means the sale is a distrato, even on the 37 rows where status_venda was never
    updated and still reads "ativa" (see module docstring).
    """
    if data_distrato:
        return False
    return norm_status_venda(status_venda) == "ativa"


def norm_nome_cliente(value: str | None) -> str:
    """Key used to group probable duplicate client records by name."""
    key = norm_key(value)
    return " ".join(key.split())


def norm_modelo_negocio(value: str | None) -> str:
    """Canonical bucket key for empreendimentos.modelo_negocio, que tem a mesma grafia
    inconsistente do resto da base: 'OBRA POR ADM', 'obra por administracao' e 'Obra por
    Administração' convivem (12 linhas), assim como 'spe incorporadora', 'incorporacao' e
    'Incorporação' (10 linhas) -- duas categorias reais atrás de 9 grafias distintas."""
    key = norm_key(value)
    if "adm" in key:
        return "obra_administracao"
    if "incorpora" in key:
        return "spe_incorporadora"
    return key


def maiusculo_sem_acento(value) -> str:
    """Formato de exibição padrão para colunas de texto na página de Dados: maiúsculo,
    sem acentuação (cedilha e vogais acentuadas viram a letra base), "--" para nulo/vazio.
    Não usada para decidir nada de negócio -- é só apresentação."""
    if value is None or value == "":
        return "--"
    return strip_accents(str(value)).upper()
