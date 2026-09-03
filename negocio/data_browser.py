"""
Página "Dados": navegador paginado de todas as tabelas de negócio (todas menos usuarios),
com as colunas de texto formatadas para exibição -- maiúsculo, sem acentuação, "--" para
nulo -- e as colunas que têm mais de uma grafia para o mesmo valor (unidades.status,
vendas.status_venda, empreendimentos.modelo_negocio) já canonicalizadas via
negocio/normalize.py.

Mesma filosofia do resto da aplicação: nada aqui reescreve o banco na hora de LER. A
formatação acontece só na hora de montar a página; o valor bruto continua intacto na
base. Duas tabelas (clientes, empreendimentos) também são editáveis por aqui -- ver
negocio/data_editor.py pra saber por que só essas duas.
"""

from dataclasses import dataclass, field
from typing import Callable

from django.core.paginator import Paginator
from django.db.models import QuerySet

from . import data_editor
from .models import Cliente, Empreendimento, FinanceiroMensal, ObraAndamento, Unidade, Venda
from .normalize import (
    CANONICAL_MODELO_NEGOCIO,
    CANONICAL_UNIDADE,
    CANONICAL_VENDA,
    maiusculo_sem_acento,
    norm_key,
    norm_modelo_negocio,
    norm_status_unidade,
    norm_status_venda,
    venda_esta_ativa,
)

LINHAS_POR_PAGINA = 25
_TABELAS_EDITAVEIS_CHAVES = frozenset(data_editor.TABELAS_EDITAVEIS)


def _texto(v) -> str:
    return maiusculo_sem_acento(v)


def _data(v) -> str:
    return v.strftime("%d/%m/%Y") if v else "--"


def _data_distrato(v: Venda) -> str:
    """Igual a _data(), mas distingue os dois motivos de vazio nesta coluna específica:
    a grande maioria (venda ainda ativa) mostra "--" normalmente; as 9 linhas onde o
    status já é "distrato" mas a data nunca foi registrada pelo sistema de origem mostram
    "SEM REGISTRO" -- ver o achado em negocio/normalize.py (docstring do módulo)."""
    if v.data_distrato:
        return _data(v.data_distrato)
    if norm_status_venda(v.status_venda) == "distrato":
        return "SEM REGISTRO"
    return "--"


def _numero(v, casas: int = 2) -> str:
    if v is None:
        return "--"
    inteiro_str = f"{v:,.{casas}f}"
    return inteiro_str.translate(str.maketrans(",.", ".,"))


def _status_unidade(v: str | None) -> str:
    return _texto(CANONICAL_UNIDADE.get(norm_status_unidade(v), v))


def _status_venda(v: Venda) -> str:
    """Diferente das outras colunas de status (que só canonicalizam a GRAFIA), esta
    aplica a regra de negócio (venda_esta_ativa()): data_distrato manda sobre o texto
    bruto de status_venda. Nas 37 linhas onde o sistema de origem não atualizou
    status_venda depois de um distrato, esta coluna mostra "DISTRATO" mesmo com o texto
    bruto dizendo "Ativa" -- ver achado em negocio/normalize.py."""
    return "ATIVA" if venda_esta_ativa(v.status_venda, v.data_distrato) else "DISTRATO"


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
        _numero(v.valor_venda, 2), _texto(v.forma_pagamento), _status_venda(v), _data_distrato(v),
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
class FiltroColuna:
    """Um filtro exibido acima da tabela. `tipo` decide tanto o controle de formulário
    quanto como `aplicar_filtros` interpreta os parâmetros de query:
      - "texto": um campo (icontains) -- parâmetro `chave`.
      - "select": um <select> com valor exato -- parâmetro `chave`, opções vêm de
        `opcoes_fn` (valores distintos já limpos, sem grafia inconsistente).
      - "select_canonico": como "select", mas pra colunas com grafia inconsistente
        (status, modelo_negocio) -- o valor do parâmetro é a CHAVE canônica (ex.:
        "vendida"), e `norm_fn` decide quais valores brutos da base pertencem a ela
        (ex.: "vendida", "Vendida", "VENDIDA").
      - "computado": como "select_canonico", mas pra uma coluna cujo valor exibido não
        vem direto de um campo (ex.: vendas.status_venda, que a tela mostra já corrigido
        por venda_esta_ativa() -- ver _status_venda) -- `calc_fn` recebe o objeto inteiro
        (não só o campo bruto) e devolve a mesma chave canônica que o valor exibido usa.
      - "numero": faixa min/máx -- parâmetros `chave_min` / `chave_max`.
      - "data": faixa de/até -- parâmetros `chave_de` / `chave_ate` (AAAA-MM-DD, o
        formato que <input type="date"> já manda).
    """

    chave: str
    rotulo: str
    tipo: str
    orm: str
    opcoes_fn: Callable[[], list[tuple[str, str]]] | None = None
    norm_fn: Callable[[str | None], str] | None = None
    calc_fn: Callable[[object], str] | None = None


def _opcoes_canonico(canonical: dict[str, str]) -> Callable[[], list[tuple[str, str]]]:
    """Opções de um filtro select_canonico: vêm direto do dicionário canônico de
    negocio/normalize.py, não precisam consultar o banco."""
    return lambda: [(chave, maiusculo_sem_acento(rotulo)) for chave, rotulo in canonical.items()]


def _opcoes_distintas(model, campo: str) -> Callable[[], list[tuple[str, str]]]:
    """Opções de um filtro select "simples": valores distintos já existentes na coluna
    (ela não tem grafia inconsistente, então o valor bruto serve de valor de filtro)."""

    def _fn() -> list[tuple[str, str]]:
        valores = model.objects.order_by().values_list(campo, flat=True).distinct()
        vistos = {v: maiusculo_sem_acento(v) for v in valores if v}
        return sorted(vistos.items(), key=lambda par: par[1])

    return _fn


def _aplicar_filtro_canonico(qs: QuerySet, orm: str, norm_fn: Callable, valor_canonico: str) -> QuerySet:
    """Filtra por uma coluna de grafia inconsistente: descobre quais valores brutos
    distintos da coluna pertencem ao bucket canônico pedido e filtra por eles (__in).
    A lista de distintos é pequena (poucas dezenas no máximo), então isso é barato."""
    distintos = qs.model.objects.order_by().values_list(orm, flat=True).distinct()
    brutos = [v for v in distintos if norm_fn(v) == valor_canonico]
    return qs.filter(**{f"{orm}__in": brutos}) if brutos else qs.none()


def _valor_orm(obj, orm_path: str):
    """Segue um caminho ORM tipo "empreendimento__nome" via getattr encadeado (os campos
    de relação já vêm resolvidos por select_related, então isso não gera query extra)."""
    valor = obj
    for parte in orm_path.split("__"):
        if valor is None:
            return None
        valor = getattr(valor, parte)
    return valor


def _aplicar_filtro_texto(qs: QuerySet, orm: str, valor: str) -> QuerySet:
    """Busca por substring ignorando acento/caixa (mesmo critério usado no resto da
    aplicação -- normalize.norm_key), diferente de um simples __icontains do Django, que
    é sensível a acento (buscar "goiania" não bateria com "Goiânia" na base). Filtra em
    Python -- nas ~3 mil linhas no máximo desta base, mais barato e muito mais simples do
    que registrar uma função SQL customizada na conexão de escrita do Django só pra isso
    (a técnica usada em nl_assistant.py, mas lá é uma conexão dedicada e só-leitura)."""
    alvo = norm_key(valor)
    ids = [obj.pk for obj in qs if alvo in norm_key(_valor_orm(obj, orm))]
    return qs.filter(pk__in=ids)


def aplicar_filtros(qs: QuerySet, filtros: list[FiltroColuna], params) -> QuerySet:
    """Aplica os filtros submetidos (querystring) sobre o queryset, antes da paginação.
    `params` é um dict-like (ex.: request.GET) -- chaves que não pertencem a nenhum
    filtro desta tabela são ignoradas."""
    for f in filtros:
        if f.tipo == "texto":
            valor = (params.get(f.chave) or "").strip()
            if valor:
                qs = _aplicar_filtro_texto(qs, f.orm, valor)
        elif f.tipo == "select":
            valor = (params.get(f.chave) or "").strip()
            if valor:
                qs = qs.filter(**{f.orm: valor})
        elif f.tipo == "select_canonico":
            valor = (params.get(f.chave) or "").strip()
            if valor:
                qs = _aplicar_filtro_canonico(qs, f.orm, f.norm_fn, valor)
        elif f.tipo == "computado":
            valor = (params.get(f.chave) or "").strip()
            if valor:
                ids = [obj.pk for obj in qs if f.calc_fn(obj) == valor]
                qs = qs.filter(pk__in=ids)
        elif f.tipo == "numero":
            minimo = (params.get(f"{f.chave}_min") or "").strip()
            maximo = (params.get(f"{f.chave}_max") or "").strip()
            if minimo:
                try:
                    qs = qs.filter(**{f"{f.orm}__gte": float(minimo.replace(",", "."))})
                except ValueError:
                    pass
            if maximo:
                try:
                    qs = qs.filter(**{f"{f.orm}__lte": float(maximo.replace(",", "."))})
                except ValueError:
                    pass
        elif f.tipo == "data":
            de = (params.get(f"{f.chave}_de") or "").strip()
            ate = (params.get(f"{f.chave}_ate") or "").strip()
            if de:
                qs = qs.filter(**{f"{f.orm}__gte": de})
            if ate:
                qs = qs.filter(**{f"{f.orm}__lte": ate})
    return qs


@dataclass
class DefinicaoTabela:
    titulo: str
    colunas: list[str]
    linha: Callable[..., list[str]]
    queryset_fn: Callable[[], QuerySet]
    filtros: list[FiltroColuna] = field(default_factory=list)


TABELAS: dict[str, DefinicaoTabela] = {
    "empreendimentos": DefinicaoTabela(
        titulo="Empreendimentos",
        colunas=["ID", "NOME", "CIDADE", "UF", "TIPO", "MODELO DE NEGÓCIO", "VGV ESTIMADO",
                 "DATA DE LANÇAMENTO", "STATUS", "OBSERVAÇÕES"],
        linha=_linha_empreendimento,
        queryset_fn=lambda: Empreendimento.objects.order_by("id"),
        filtros=[
            FiltroColuna("nome", "Nome", "texto", "nome"),
            FiltroColuna("cidade", "Cidade", "texto", "cidade"),
            FiltroColuna("uf", "UF", "select", "uf", _opcoes_distintas(Empreendimento, "uf")),
            FiltroColuna("tipo", "Tipo", "select", "tipo", _opcoes_distintas(Empreendimento, "tipo")),
            FiltroColuna("modelo_negocio", "Modelo de negócio", "select_canonico", "modelo_negocio",
                         _opcoes_canonico(CANONICAL_MODELO_NEGOCIO), norm_modelo_negocio),
            FiltroColuna("vgv_estimado", "VGV estimado", "numero", "vgv_estimado"),
            FiltroColuna("data_lancamento", "Data de lançamento", "data", "data_lancamento"),
            FiltroColuna("status", "Status", "select", "status", _opcoes_distintas(Empreendimento, "status")),
            FiltroColuna("observacoes", "Observações", "texto", "observacoes"),
        ],
    ),
    "unidades": DefinicaoTabela(
        titulo="Unidades",
        colunas=["ID", "EMPREENDIMENTO", "IDENTIFICADOR", "TIPO", "ÁREA PRIVATIVA (M²)",
                 "VALOR DE TABELA", "STATUS"],
        linha=_linha_unidade,
        queryset_fn=lambda: Unidade.objects.select_related("empreendimento").order_by("id"),
        filtros=[
            FiltroColuna("empreendimento", "Empreendimento", "texto", "empreendimento__nome"),
            FiltroColuna("identificador", "Identificador", "texto", "identificador"),
            FiltroColuna("tipo", "Tipo", "select", "tipo", _opcoes_distintas(Unidade, "tipo")),
            FiltroColuna("area", "Área privativa (m²)", "numero", "area_privativa_m2"),
            FiltroColuna("valor_tabela", "Valor de tabela", "numero", "valor_tabela"),
            FiltroColuna("status", "Status", "select_canonico", "status",
                         _opcoes_canonico(CANONICAL_UNIDADE), norm_status_unidade),
        ],
    ),
    "clientes": DefinicaoTabela(
        titulo="Clientes",
        colunas=["ID", "NOME", "CIDADE", "UF", "PERFIL", "DATA DE CADASTRO", "E-MAIL"],
        linha=_linha_cliente,
        queryset_fn=lambda: Cliente.objects.order_by("id"),
        filtros=[
            FiltroColuna("nome", "Nome", "texto", "nome"),
            FiltroColuna("cidade", "Cidade", "texto", "cidade"),
            FiltroColuna("uf", "UF", "select", "uf", _opcoes_distintas(Cliente, "uf")),
            FiltroColuna("perfil", "Perfil", "select", "perfil", _opcoes_distintas(Cliente, "perfil")),
            FiltroColuna("data_cadastro", "Data de cadastro", "data", "data_cadastro"),
            FiltroColuna("email", "E-mail", "texto", "email"),
        ],
    ),
    "vendas": DefinicaoTabela(
        titulo="Vendas",
        colunas=["ID", "UNIDADE", "CLIENTE", "DATA DA VENDA", "VALOR", "FORMA DE PAGAMENTO",
                 "STATUS", "DATA DE DISTRATO"],
        linha=_linha_venda,
        queryset_fn=lambda: Venda.objects.select_related("unidade", "cliente").order_by("id"),
        filtros=[
            FiltroColuna("unidade", "Unidade", "texto", "unidade__identificador"),
            FiltroColuna("cliente", "Cliente", "texto", "cliente__nome"),
            FiltroColuna("data_venda", "Data da venda", "data", "data_venda"),
            FiltroColuna("valor_venda", "Valor", "numero", "valor_venda"),
            FiltroColuna("forma_pagamento", "Forma de pagamento", "select", "forma_pagamento",
                         _opcoes_distintas(Venda, "forma_pagamento")),
            FiltroColuna("status_venda", "Status", "computado", "status_venda",
                         _opcoes_canonico(CANONICAL_VENDA),
                         calc_fn=lambda v: "ativa" if venda_esta_ativa(v.status_venda, v.data_distrato) else "distrato"),
            FiltroColuna("data_distrato", "Data de distrato", "data", "data_distrato"),
        ],
    ),
    "obra_andamento": DefinicaoTabela(
        titulo="Obra andamento",
        colunas=["ID", "EMPREENDIMENTO", "MÊS DE REFERÊNCIA", "% CONCLUSÃO", "CUSTO ORÇADO",
                 "CUSTO REALIZADO", "OBSERVAÇÕES"],
        linha=_linha_obra,
        queryset_fn=lambda: ObraAndamento.objects.select_related("empreendimento").order_by("id"),
        filtros=[
            FiltroColuna("empreendimento", "Empreendimento", "texto", "empreendimento__nome"),
            FiltroColuna("mes_referencia", "Mês de referência", "data", "mes_referencia"),
            FiltroColuna("percentual_conclusao", "% conclusão", "numero", "percentual_conclusao"),
            FiltroColuna("custo_orcado_mes", "Custo orçado", "numero", "custo_orcado_mes"),
            FiltroColuna("custo_realizado_mes", "Custo realizado", "numero", "custo_realizado_mes"),
            FiltroColuna("observacoes", "Observações", "texto", "observacoes"),
        ],
    ),
    "financeiro_mensal": DefinicaoTabela(
        titulo="Financeiro mensal",
        colunas=["ID", "EMPREENDIMENTO", "MÊS DE REFERÊNCIA", "RECEITA RECONHECIDA",
                 "CUSTO INCORRIDO", "DESPESAS RATEADAS", "RESULTADO REPORTADO"],
        linha=_linha_financeiro,
        queryset_fn=lambda: FinanceiroMensal.objects.select_related("empreendimento").order_by("id"),
        filtros=[
            FiltroColuna("empreendimento", "Empreendimento", "texto", "empreendimento__nome"),
            FiltroColuna("mes_referencia", "Mês de referência", "data", "mes_referencia"),
            FiltroColuna("receita_reconhecida", "Receita reconhecida", "numero", "receita_reconhecida"),
            FiltroColuna("custo_incorrido", "Custo incorrido", "numero", "custo_incorrido"),
            FiltroColuna("despesas_corporativas_rat", "Despesas rateadas", "numero", "despesas_corporativas_rat"),
            FiltroColuna("resultado_reportado", "Resultado reportado", "numero", "resultado_reportado"),
        ],
    ),
}

ORDEM_TABELAS = [
    "empreendimentos", "unidades", "clientes", "vendas", "obra_andamento", "financeiro_mensal",
]


@dataclass
class FiltroExibicao:
    """Metadados de um filtro já resolvidos para o template (opções calculadas)."""

    chave: str
    rotulo: str
    tipo: str
    opcoes: list[tuple[str, str]] | None


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
    filtros: list[FiltroExibicao]
    filtros_valores: dict[str, str]
    filtros_ativos: bool
    editavel: bool


def carregar_pagina(chave: str, pagina: int = 1, params=None) -> PaginaTabela:
    """`params` é um dict-like (tipicamente request.GET) com os valores de filtro
    submetidos -- ver FiltroColuna/aplicar_filtros para o formato de cada chave."""
    definicao = TABELAS[chave]
    params = params or {}
    qs = aplicar_filtros(definicao.queryset_fn(), definicao.filtros, params)
    paginator = Paginator(qs, LINHAS_POR_PAGINA)
    pagina = max(1, min(pagina, paginator.num_pages or 1))
    page_obj = paginator.page(pagina)
    filtros_valores = {f.chave: params.get(f.chave, "") for f in definicao.filtros}
    filtros_valores.update({
        chave_extra: params.get(chave_extra, "")
        for f in definicao.filtros
        for chave_extra in (f"{f.chave}_min", f"{f.chave}_max", f"{f.chave}_de", f"{f.chave}_ate")
        if params.get(chave_extra)
    })
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
        filtros=[
            FiltroExibicao(f.chave, f.rotulo, f.tipo, f.opcoes_fn() if f.opcoes_fn else None)
            for f in definicao.filtros
        ],
        filtros_valores=filtros_valores,
        filtros_ativos=any(v for v in filtros_valores.values()),
        editavel=chave in _TABELAS_EDITAVEIS_CHAVES,
    )
