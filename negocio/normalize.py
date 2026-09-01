"""
Canonicalization rules for the messy free-text fields in the base.

The source data mixes casing and spelling for the same underlying concept
(e.g. unit status appears as "vendida", "Vendida", "VENDIDA"). Historical rows are never
rewritten in place -- callers normalize at read time using the helpers below, and new
rows written by this app (negocio/services.py) always use the canonical spelling.

STATUS_UNIDADE canon: disponivel | reservada | vendida | distrato | cancelado
STATUS_VENDA canon:   ativa | distrato

Finding: every unit with canonical status "cancelado" has a linked sale with canonical
status "distrato" (verified against the source base), i.e. "cancelado" and "distrato" are
two different historical spellings for the same outcome: a unit whose sale fell through
and that was never put back on the market. Both are treated as "not available for sale"
in analytics. Going forward this app follows the brief's explicit rule instead: a distrato
returns the unit to "disponivel" so it re-enters the sellable pool.
"""

import unicodedata

CANONICAL_UNIDADE = {
    "disponivel": "Disponível",
    "reservada": "Reservada",
    "vendida": "Vendida",
    "distrato": "Distrato",
    "cancelado": "Cancelado",
}

CANONICAL_VENDA = {
    "ativa": "Ativa",
    "distrato": "Distrato",
}

# Statuses (already normalized) that make a unit ineligible for a new sale.
UNIDADE_INDISPONIVEL = {"reservada", "vendida", "distrato", "cancelado"}


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
    """Return the canonical bucket key (e.g. 'vendida') for a raw unidades.status value."""
    key = norm_key(value)
    if key in ("vendida",):
        return "vendida"
    if key in ("distrato",):
        return "distrato"
    if key in ("cancelado",):
        return "cancelado"
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


def norm_nome_cliente(value: str | None) -> str:
    """Key used to group probable duplicate client records by name."""
    key = norm_key(value)
    return " ".join(key.split())
