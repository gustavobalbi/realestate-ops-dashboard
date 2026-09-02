"""
Página "Dados": navegador somente-leitura e paginado de todas as tabelas de negócio
(todas menos usuarios), com as colunas de texto formatadas para exibição -- maiúsculo,
sem acentuação, "--" para nulo -- e as colunas que têm mais de uma grafia para o mesmo
valor (unidades.status, vendas.status_venda, empreendimentos.modelo_negocio) já
canonicalizadas via negocio/normalize.py.

Mesma filosofia do resto da aplicação: nada aqui reescreve o banco. A formatação acontece
só na hora de montar a página; o valor bruto continua intacto na base.
"""

from dataclasses import dataclass
from typing import Callable

from django.core.paginator import Paginator
from django.db.models import QuerySet

from .models import Cliente, Empreendimento, FinanceiroMensal, ObraAndamento, Unidade, Venda
from .normalize import (
    CANONICAL_MODELO_NEGOCIO,
    CANONICAL_UNIDADE,
    CANONICAL_VENDA,
    maiusculo_sem_acento,
    norm_modelo_negocio,
    norm_status_unidade,
    norm_status_venda,
)

LINHAS_POR_PAGINA = 25


def _texto(v) -> str:
    return maiusculo_sem_acento(v)


def _data(v) -> str:
    return v.strftime("%d/%m/%Y") if v else "--"


def _numero(v, casas: int = 2) -> str:
    if v is None:
        return "--"
    inteiro_str = f"{v:,.{casas}f}"
    return inteiro_str.translate(str.maketrans(",.", ".,"))


def _status_unidade(v: str | None) -> str:
    return _texto(CANONICAL_UNIDADE.get(norm_status_unidade(v), v))


def _status_venda(v: str | None) -> str:
    return _texto(CANONICAL_VENDA.get(norm_status_venda(v), v))


def _modelo_negocio(v: str | None) -> str:
    return _texto(CANONICAL_MODELO_NEGOCIO.get(norm_modelo_negocio(v), v))


def _linha_empreendimento(e: Empreendimento) -> list[str]:
    return [
        str(e.id), _texto(e.nome), _texto(e.cidade), _texto(e.uf), _texto(e.tipo),
        _modelo_negocio(e.modelo_negocio), _numero(e.vgv_estimado, 0), _data(e.data_lancamento),
        _texto(e.status), _texto(e.observacoes),
    ]


def _linha_unidade(u: Unidade) -> list[str]:
    return [
        str(u.id), _texto(u.empreendimento.nome), _texto(u.identificador), _texto(u.tipo),
        _numero(u.area_privativa_m2, 1), _numero(u.valor_tabela, 2), _status_unidade(u.status),
    ]


def _linha_cliente(c: Cliente) -> list[str]:
    return [
        str(c.id), _texto(c.nome), _texto(c.cidade), _texto(c.uf), _texto(c.perfil),
        _data(c.data_cadastro), _texto(c.email),
    ]


def _linha_venda(v: Venda) -> list[str]:
    return [
        str(v.id), _texto(v.unidade.identificador), _texto(v.cliente.nome), _data(v.data_venda),
        _numero(v.valor_venda, 2), _texto(v.forma_pagamento), _status_venda(v.status_venda),
        _data(v.data_distrato),
    ]


def _linha_obra(o: ObraAndamento) -> list[str]:
    return [
        str(o.id), _texto(o.empreendimento.nome), _data(o.mes_referencia),
        _numero(o.percentual_conclusao, 2), _numero(o.custo_orcado_mes, 2),
        _numero(o.custo_realizado_mes, 2), _texto(o.observacoes),
    ]


def _linha_financeiro(f: FinanceiroMensal) -> list[str]:
    return [
        str(f.id), _texto(f.empreendimento.nome), _data(f.mes_referencia),
        _numero(f.receita_reconhecida, 2), _numero(f.custo_incorrido, 2),
        _numero(f.despesas_corporativas_rat, 2), _numero(f.resultado_reportado, 2),
    ]


@dataclass
class DefinicaoTabela:
    titulo: str
    colunas: list[str]
    linha: Callable[..., list[str]]
    queryset_fn: Callable[[], QuerySet]


TABELAS: dict[str, DefinicaoTabela] = {
    "empreendimentos": DefinicaoTabela(
        titulo="Empreendimentos",
        colunas=["ID", "NOME", "CIDADE", "UF", "TIPO", "MODELO DE NEGÓCIO", "VGV ESTIMADO",
                 "DATA DE LANÇAMENTO", "STATUS", "OBSERVAÇÕES"],
        linha=_linha_empreendimento,
        queryset_fn=lambda: Empreendimento.objects.order_by("id"),
    ),
    "unidades": DefinicaoTabela(
        titulo="Unidades",
        colunas=["ID", "EMPREENDIMENTO", "IDENTIFICADOR", "TIPO", "ÁREA PRIVATIVA (M²)",
                 "VALOR DE TABELA", "STATUS"],
        linha=_linha_unidade,
        queryset_fn=lambda: Unidade.objects.select_related("empreendimento").order_by("id"),
    ),
    "clientes": DefinicaoTabela(
        titulo="Clientes",
        colunas=["ID", "NOME", "CIDADE", "UF", "PERFIL", "DATA DE CADASTRO", "E-MAIL"],
        linha=_linha_cliente,
        queryset_fn=lambda: Cliente.objects.order_by("id"),
    ),
    "vendas": DefinicaoTabela(
        titulo="Vendas",
        colunas=["ID", "UNIDADE", "CLIENTE", "DATA DA VENDA", "VALOR", "FORMA DE PAGAMENTO",
                 "STATUS", "DATA DE DISTRATO"],
        linha=_linha_venda,
        queryset_fn=lambda: Venda.objects.select_related("unidade", "cliente").order_by("id"),
    ),
    "obra_andamento": DefinicaoTabela(
        titulo="Obra andamento",
        colunas=["ID", "EMPREENDIMENTO", "MÊS DE REFERÊNCIA", "% CONCLUSÃO", "CUSTO ORÇADO",
                 "CUSTO REALIZADO", "OBSERVAÇÕES"],
        linha=_linha_obra,
        queryset_fn=lambda: ObraAndamento.objects.select_related("empreendimento").order_by("id"),
    ),
    "financeiro_mensal": DefinicaoTabela(
        titulo="Financeiro mensal",
        colunas=["ID", "EMPREENDIMENTO", "MÊS DE REFERÊNCIA", "RECEITA RECONHECIDA",
                 "CUSTO INCORRIDO", "DESPESAS RATEADAS", "RESULTADO REPORTADO"],
        linha=_linha_financeiro,
        queryset_fn=lambda: FinanceiroMensal.objects.select_related("empreendimento").order_by("id"),
    ),
}

ORDEM_TABELAS = [
    "empreendimentos", "unidades", "clientes", "vendas", "obra_andamento", "financeiro_mensal",
]


@dataclass
class PaginaTabela:
    chave: str
    titulo: str
    colunas: list[str]
    linhas: list[list[str]]
    pagina_atual: int
    total_paginas: int
    total_linhas: int
    tem_anterior: bool
    tem_proxima: bool


def carregar_pagina(chave: str, pagina: int = 1) -> PaginaTabela:
    definicao = TABELAS[chave]
    paginator = Paginator(definicao.queryset_fn(), LINHAS_POR_PAGINA)
    pagina = max(1, min(pagina, paginator.num_pages or 1))
    page_obj = paginator.page(pagina)
    return PaginaTabela(
        chave=chave,
        titulo=definicao.titulo,
        colunas=definicao.colunas,
        linhas=[definicao.linha(obj) for obj in page_obj.object_list],
        pagina_atual=page_obj.number,
        total_paginas=paginator.num_pages,
        total_linhas=paginator.count,
        tem_anterior=page_obj.has_previous(),
        tem_proxima=page_obj.has_next(),
    )
