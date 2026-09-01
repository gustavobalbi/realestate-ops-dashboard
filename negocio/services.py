"""
Write layer: register a sale, register a distrato (sale cancellation). Each function
runs inside a transaction and re-checks the business rule against the current row
(select_for_update) so a concurrent request can't sell the same unit twice.
"""

import datetime as dt

from django.db import transaction

from .models import Cliente, Unidade, Venda
from .normalize import UNIDADE_INDISPONIVEL, norm_status_unidade, norm_status_venda


class RegraDeNegocioError(Exception):
    """Raised when an action would violate a business rule (e.g. selling a sold unit)."""


@transaction.atomic
def registrar_venda(
    *,
    unidade_id: int,
    cliente_id: int | None,
    cliente_novo: dict | None,
    valor_venda: float,
    forma_pagamento: str,
    data_venda: dt.date | None = None,
) -> Venda:
    unidade = Unidade.objects.select_for_update().get(id=unidade_id)
    if norm_status_unidade(unidade.status) in UNIDADE_INDISPONIVEL:
        raise RegraDeNegocioError(
            f"A unidade {unidade.identificador} não está disponível "
            f"(status atual: {unidade.status})."
        )

    if cliente_id:
        cliente = Cliente.objects.get(id=cliente_id)
    elif cliente_novo:
        cliente = Cliente.objects.create(
            nome=cliente_novo["nome"],
            cidade=cliente_novo.get("cidade") or "",
            uf=cliente_novo.get("uf") or "",
            perfil=cliente_novo.get("perfil") or "",
            data_cadastro=(data_venda or dt.date.today()).isoformat(),
            email=cliente_novo.get("email") or "",
        )
    else:
        raise RegraDeNegocioError("Informe um cliente existente ou os dados de um novo cliente.")

    venda = Venda.objects.create(
        unidade=unidade,
        cliente=cliente,
        data_venda=(data_venda or dt.date.today()).isoformat(),
        valor_venda=valor_venda,
        forma_pagamento=forma_pagamento,
        status_venda="Ativa",
        data_distrato=None,
    )

    unidade.status = "Vendida"
    unidade.save(update_fields=["status"])
    return venda


@transaction.atomic
def registrar_distrato(*, venda_id: int, data_distrato: dt.date | None = None) -> Venda:
    venda = Venda.objects.select_related("unidade").select_for_update().get(id=venda_id)
    if norm_status_venda(venda.status_venda) != "ativa":
        raise RegraDeNegocioError(
            f"A venda #{venda.id} não está ativa (status atual: {venda.status_venda})."
        )

    venda.status_venda = "Distrato"
    venda.data_distrato = (data_distrato or dt.date.today()).isoformat()
    venda.save(update_fields=["status_venda", "data_distrato"])

    unidade = Unidade.objects.select_for_update().get(id=venda.unidade_id)
    # Regra do briefing: o distrato devolve a unidade ao status correto, isto é,
    # disponível para uma nova venda -- diferente do padrão histórico da base (ver
    # negocio/normalize.py), que deixava a unidade marcada como "Distrato"/"Cancelado".
    unidade.status = "Disponível"
    unidade.save(update_fields=["status"])
    return venda
