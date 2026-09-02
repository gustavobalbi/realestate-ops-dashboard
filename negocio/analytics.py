"""
Business-question logic (test brief, section 4). Every function documents the premise it
adopts where the brief leaves the definition open, and returns plain dicts/lists so views
and templates stay simple.
"""

import math
from collections import defaultdict
from dataclasses import dataclass, field

from . import geo
from .models import Cliente, Empreendimento, FinanceiroMensal, ObraAndamento, Unidade, Venda
from .normalize import norm_key, norm_nome_cliente, norm_status_unidade, venda_esta_ativa

MISMATCH_TOLERANCE = 0.01  # R$ rounding tolerance for the financeiro recalculation check


# ---------------------------------------------------------------------------
# 1) Velocidade de vendas por empreendimento
# ---------------------------------------------------------------------------
#
# Premissa: "unidades ofertadas" = todas as unidades cadastradas para o empreendimento
# (o estoque total colocado à venda), independente do status atual. "Vendidas líquidas de
# distrato" = vendas ativas segundo venda_esta_ativa() (normalize.py): data_distrato
# preenchida sempre conta como distrato, mesmo nas 37 linhas em que status_venda ainda diz
# "ativa" -- achado de qualidade de dados de que o sistema de origem falhou em atualizar
# esse campo. velocidade = vendas_ativas / total_unidades.


@dataclass
class VelocidadeVendas:
    empreendimento: Empreendimento
    total_unidades: int
    vendas_ativas: int
    velocidade: float


def velocidade_vendas() -> list[VelocidadeVendas]:
    empreendimentos = {e.id: e for e in Empreendimento.objects.all()}
    total_unidades = defaultdict(int)
    for u in _unidades_all():
        total_unidades[u.empreendimento_id] += 1

    vendas_ativas = defaultdict(int)
    for v in Venda.objects.select_related("unidade").all():
        if venda_esta_ativa(v.status_venda, v.data_distrato):
            vendas_ativas[v.unidade.empreendimento_id] += 1

    resultado = []
    for emp_id, emp in empreendimentos.items():
        total = total_unidades.get(emp_id, 0)
        ativas = vendas_ativas.get(emp_id, 0)
        velocidade = (ativas / total * 100) if total else 0.0
        resultado.append(VelocidadeVendas(emp, total, ativas, velocidade))
    resultado.sort(key=lambda r: r.velocidade)
    return resultado


def _unidades_all():
    from .models import Unidade

    return Unidade.objects.only("id", "empreendimento_id").all()


@dataclass
class BarraVelocidade:
    item: VelocidadeVendas
    pior: bool
    altura_pct: float  # 0-100, relative to the highest velocidade in the set


def velocidade_chart(n_piores: int = 3) -> list[BarraVelocidade]:
    """Descending left-to-right (best first), last n_piores flagged for the red highlight."""
    itens = sorted(velocidade_vendas(), key=lambda r: r.velocidade, reverse=True)
    maior = itens[0].velocidade if itens else 0.0
    total = len(itens)
    return [
        BarraVelocidade(
            item=it,
            pior=(total - i) <= n_piores,
            altura_pct=(it.velocidade / maior * 100) if maior else 0.0,
        )
        for i, it in enumerate(itens)
    ]


# ---------------------------------------------------------------------------
# 2) Risco de estouro de custo
# ---------------------------------------------------------------------------
#
# Premissa: para cada empreendimento, soma-se custo_realizado_mes e custo_orcado_mes de
# todas as medições em obra_andamento. Estouro = custo realizado acumulado > custo
# orçado acumulado. Magnitude = diferença acumulada (realizado - orçado); positiva
# indica estouro, negativa indica economia frente ao orçado.


@dataclass
class RiscoCusto:
    empreendimento: Empreendimento
    custo_orcado: float
    custo_realizado: float
    magnitude: float
    percentual: float


def risco_estouro_custo() -> list[RiscoCusto]:
    empreendimentos = {e.id: e for e in Empreendimento.objects.all()}
    orcado = defaultdict(float)
    realizado = defaultdict(float)
    for m in ObraAndamento.objects.all():
        orcado[m.empreendimento_id] += m.custo_orcado_mes or 0.0
        realizado[m.empreendimento_id] += m.custo_realizado_mes or 0.0

    resultado = []
    for emp_id in orcado.keys() | realizado.keys():
        emp = empreendimentos.get(emp_id)
        if emp is None:
            continue
        o, r = orcado[emp_id], realizado[emp_id]
        magnitude = r - o
        percentual = (magnitude / o * 100) if o else 0.0
        resultado.append(RiscoCusto(emp, o, r, magnitude, percentual))
    resultado.sort(key=lambda r: r.magnitude, reverse=True)
    return resultado


def em_estouro(lista: list[RiscoCusto]) -> list[RiscoCusto]:
    return [r for r in lista if r.magnitude > 0]


@dataclass
class BarraRisco:
    item: RiscoCusto
    acima_da_media: bool
    largura_pct: float  # 0-100, relative to the largest overrun magnitude


def risco_chart() -> tuple[list[BarraRisco], float]:
    """Descending top-to-bottom, highlighting bars above the mean overrun magnitude.

    Returns (barras, media_magnitude).
    """
    itens = em_estouro(risco_estouro_custo())  # already sorted desc by magnitude
    if not itens:
        return [], 0.0
    media = sum(r.magnitude for r in itens) / len(itens)
    maior = itens[0].magnitude
    barras = [
        BarraRisco(
            item=it,
            acima_da_media=it.magnitude > media,
            largura_pct=(it.magnitude / maior * 100) if maior else 0.0,
        )
        for it in itens
    ]
    return barras, media


# ---------------------------------------------------------------------------
# 3) Clientes potencialmente duplicados
# ---------------------------------------------------------------------------
#
# A base não tem CPF/telefone, mas tem e-mail -- e o e-mail é uma chave de fato distinta
# aqui: 2691 clientes, 2691 e-mails distintos (mesmo normalizando caixa/espaços). Ou seja,
# **não há indício de cadastro duplicado nesta base** quando se usa uma chave própria.
#
# O que existe são homônimos: vários clientes com o mesmo nome, mas e-mail (e geralmente
# cidade) diferentes -- pessoas distintas. Uma dedup ingênua por nome, como uma primeira
# versão deste dashboard chegou a fazer, mescla essas pessoas por engano e distorce a
# métrica de ticket médio por cliente para baixo (menos "clientes" dividindo a mesma
# receita). A tabela abaixo mostra essa distorção lado a lado com o valor correto, e cada
# homônimo aparece como "Nome — Cidade/UF" para deixar claro que são cadastros diferentes.


@dataclass
class GrupoHomonimos:
    chave_nome: str
    clientes: list[Cliente]


@dataclass
class AnaliseClientes:
    total_clientes: int
    emails_distintos: int
    duplicados_reais: list[GrupoHomonimos]  # mesmo e-mail normalizado -- esperado vazio
    homonimos: list[GrupoHomonimos]  # mesmo nome, e-mails diferentes -- pessoas distintas
    ticket_medio_correto: float  # receita total / clientes únicos por e-mail (correto)
    ticket_medio_ingenuo_por_nome: float  # o que uma dedup errada por nome produziria


def nome_com_localizacao(cliente: Cliente) -> str:
    local = "/".join(p for p in (cliente.cidade, cliente.uf) if p)
    return f"{cliente.nome} — {local}" if local else cliente.nome


def clientes_duplicados() -> AnaliseClientes:
    clientes = list(Cliente.objects.all())

    por_email: dict[str, list[Cliente]] = defaultdict(list)
    for c in clientes:
        por_email[norm_key(c.email)].append(c)
    duplicados_reais = [
        GrupoHomonimos(chave, lista) for chave, lista in por_email.items() if len(lista) > 1
    ]

    por_nome: dict[str, list[Cliente]] = defaultdict(list)
    for c in clientes:
        por_nome[norm_nome_cliente(c.nome)].append(c)
    homonimos = [
        GrupoHomonimos(chave, lista) for chave, lista in por_nome.items() if len(lista) > 1
    ]
    homonimos.sort(key=lambda g: -len(g.clientes))

    valor_por_cliente: dict[int, float] = defaultdict(float)
    for v in Venda.objects.only("cliente_id", "valor_venda").all():
        valor_por_cliente[v.cliente_id] += v.valor_venda
    receita_total = sum(valor_por_cliente.values())

    # Correto: cada cliente_id é uma pessoa distinta (confirmado pelo e-mail único).
    n_compradores_correto = len(valor_por_cliente)

    # Ilustração do erro: se agrupássemos por nome (tratando homônimos como duplicados),
    # o número de "clientes" cairia e o ticket médio subiria artificialmente.
    canonico_por_nome: dict[int, int] = {}
    for g in homonimos:
        canon = min(c.id for c in g.clientes)
        for c in g.clientes:
            canonico_por_nome[c.id] = canon
    valor_por_cliente_ingenuo: dict[int, float] = defaultdict(float)
    for cid, valor in valor_por_cliente.items():
        canon = canonico_por_nome.get(cid, cid)
        valor_por_cliente_ingenuo[canon] += valor
    n_compradores_ingenuo = len(valor_por_cliente_ingenuo)

    return AnaliseClientes(
        total_clientes=len(clientes),
        emails_distintos=len(por_email),
        duplicados_reais=duplicados_reais,
        homonimos=homonimos,
        ticket_medio_correto=(receita_total / n_compradores_correto)
        if n_compradores_correto
        else 0.0,
        ticket_medio_ingenuo_por_nome=(receita_total / n_compradores_ingenuo)
        if n_compradores_ingenuo
        else 0.0,
    )


# ---------------------------------------------------------------------------
# 4) Inconsistência financeiro reportado vs. recalculado
# ---------------------------------------------------------------------------
#
# recalculado = receita_reconhecida - custo_incorrido - despesas_corporativas_rat
# Uma linha é inconsistente quando |recalculado - resultado_reportado| > tolerância
# (usamos R$ 0,01 para absorver arredondamento de ponto flutuante).


@dataclass
class InconsistenciaFinanceira:
    empreendimento: Empreendimento
    mes_referencia: str
    resultado_reportado: float
    resultado_recalculado: float
    diferenca: float


def inconsistencias_financeiro() -> list[InconsistenciaFinanceira]:
    empreendimentos = {e.id: e for e in Empreendimento.objects.all()}
    resultado = []
    for f in FinanceiroMensal.objects.all():
        recalc = f.receita_reconhecida - f.custo_incorrido - f.despesas_corporativas_rat
        diff = recalc - f.resultado_reportado
        if abs(diff) > MISMATCH_TOLERANCE:
            resultado.append(
                InconsistenciaFinanceira(
                    empreendimentos[f.empreendimento_id],
                    f.mes_referencia,
                    f.resultado_reportado,
                    recalc,
                    diff,
                )
            )
    resultado.sort(key=lambda r: abs(r.diferenca), reverse=True)
    return resultado


# ---------------------------------------------------------------------------
# Mapa de navegação (não é uma das 4 perguntas -- visão geográfica auxiliar)
# ---------------------------------------------------------------------------


@dataclass
class EmpreendimentoResumo:
    nome: str
    tipo: str
    cidade: str
    uf: str
    unidades_disponiveis: int


@dataclass
class MarcadorMapa:
    cidade: str
    uf: str
    x: float
    y: float
    raio: float
    empreendimentos: list[EmpreendimentoResumo] = field(default_factory=list)


def _raio_marcador(n_empreendimentos: int) -> float:
    """Raio em px do círculo do marcador, crescendo com a raiz do nº de empreendimentos."""
    return 24 + 32 * math.sqrt(n_empreendimentos)


def _afastar_marcadores_sobrepostos(
    pontos: list[dict], iteracoes: int = 300, folga: float = 6.0
) -> None:
    """Empurra marcadores cujos círculos se sobrepõem para longe um do outro, em pares,
    até não haver mais sobreposição (ou esgotar as iterações). Cidades geograficamente
    próximas (ex.: Belém/Ananindeua/Marituba, a poucos km uma da outra) ficam a poucos
    pixels de distância neste mapa e, sem isso, o marcador de uma fica escondido atrás do
    de outra -- normalize.py documenta achados de dados; este é um achado sobre a própria
    visualização, não sobre a base."""
    for _ in range(iteracoes):
        moveu = False
        for i in range(len(pontos)):
            for j in range(i + 1, len(pontos)):
                a, b = pontos[i], pontos[j]
                dx = b["x"] - a["x"]
                dy = b["y"] - a["y"]
                dist = math.hypot(dx, dy)
                dist_minima = a["raio"] + b["raio"] + folga
                if dist < dist_minima:
                    moveu = True
                    if dist < 1e-6:
                        ux, uy, dist = 1.0, 0.0, 1.0
                    else:
                        ux, uy = dx / dist, dy / dist
                    empurrao = (dist_minima - dist) / 2
                    a["x"] -= ux * empurrao
                    a["y"] -= uy * empurrao
                    b["x"] += ux * empurrao
                    b["y"] += uy * empurrao
        if not moveu:
            break


def mapa_marcadores() -> list[MarcadorMapa]:
    unidades_disponiveis: dict[int, int] = defaultdict(int)
    for u in Unidade.objects.only("id", "empreendimento_id", "status"):
        if norm_status_unidade(u.status) == "disponivel":
            unidades_disponiveis[u.empreendimento_id] += 1

    por_cidade: dict[tuple[str, str], list[Empreendimento]] = defaultdict(list)
    for e in Empreendimento.objects.all():
        por_cidade[(e.cidade, e.uf)].append(e)

    pontos = []
    for (cidade, uf), emps in por_cidade.items():
        coords = geo.CITY_COORDS.get(cidade)
        if coords is None:
            continue
        x, y = geo.project(*coords)
        resumos = [
            EmpreendimentoResumo(
                nome=e.nome,
                tipo=e.tipo,
                cidade=cidade,
                uf=uf,
                unidades_disponiveis=unidades_disponiveis.get(e.id, 0),
            )
            for e in emps
        ]
        pontos.append(
            {
                "cidade": cidade,
                "uf": uf,
                "x": x,
                "y": y,
                "raio": _raio_marcador(len(emps)),
                "empreendimentos": resumos,
            }
        )

    _afastar_marcadores_sobrepostos(pontos)

    return [
        MarcadorMapa(
            cidade=p["cidade"],
            uf=p["uf"],
            x=p["x"],
            y=p["y"],
            raio=p["raio"],
            empreendimentos=p["empreendimentos"],
        )
        for p in pontos
    ]
