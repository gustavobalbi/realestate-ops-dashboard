"""
Business-question logic (test brief, section 4). Every function documents the premise it
adopts where the brief leaves the definition open, and returns plain dicts/lists so views
and templates stay simple.
"""

from collections import defaultdict
from dataclasses import dataclass

from .models import Cliente, Empreendimento, FinanceiroMensal, ObraAndamento, Venda
from .normalize import norm_nome_cliente, norm_status_venda

MISMATCH_TOLERANCE = 0.01  # R$ rounding tolerance for the financeiro recalculation check


# ---------------------------------------------------------------------------
# 1) Velocidade de vendas por empreendimento
# ---------------------------------------------------------------------------
#
# Premissa: "unidades ofertadas" = todas as unidades cadastradas para o empreendimento
# (o estoque total colocado à venda), independente do status atual. "Vendidas líquidas de
# distrato" = vendas cujo status normalizado é "ativa" (uma venda distratada não conta,
# mesmo que a unidade nunca tenha voltado ao estoque disponível no cadastro histórico).
# velocidade = vendas_ativas / total_unidades.


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
        if norm_status_venda(v.status_venda) == "ativa":
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


def piores_velocidades(n: int = 3) -> list[VelocidadeVendas]:
    return velocidade_vendas()[:n]


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


# ---------------------------------------------------------------------------
# 3) Clientes potencialmente duplicados
# ---------------------------------------------------------------------------
#
# Premissa: dois cadastros de clientes são um provável duplicado quando o nome, após
# remover acentuação/espacos extras e normalizar caixa, é idêntico. É uma regra
# conservadora (não pega erros de digitação no nome), escolhida para minimizar falsos
# positivos numa amostra sem CPF/telefone para conferência cruzada.


@dataclass
class GrupoDuplicado:
    chave_nome: str
    clientes: list[Cliente]


@dataclass
class ImpactoDuplicidade:
    grupos_duplicados: list[GrupoDuplicado]
    registros_duplicados: int  # registros "extras" além do 1 canônico por grupo
    clientes_unicos_bruto: int
    clientes_unicos_tratado: int
    ticket_medio_bruto: float
    ticket_medio_tratado: float


def clientes_duplicados() -> ImpactoDuplicidade:
    clientes = list(Cliente.objects.all())
    por_chave: dict[str, list[Cliente]] = defaultdict(list)
    for c in clientes:
        por_chave[norm_nome_cliente(c.nome)].append(c)

    grupos = [
        GrupoDuplicado(chave, lista) for chave, lista in por_chave.items() if len(lista) > 1
    ]
    grupos.sort(key=lambda g: -len(g.clientes))

    registros_duplicados = sum(len(g.clientes) - 1 for g in grupos)

    # id canônico por cliente: o menor id do grupo de duplicados (ou o próprio id se não
    # houver duplicidade) -- usado para "mesclar" clientes na análise sem alterar a base.
    canonico_por_id: dict[int, int] = {}
    for g in grupos:
        canon = min(c.id for c in g.clientes)
        for c in g.clientes:
            canonico_por_id[c.id] = canon

    # "Ticket médio por cliente" = receita total / número de clientes únicos que compraram.
    # A receita total das vendas não muda ao mesclar duplicados -- só o denominador muda,
    # o que é exatamente a distorção que a pergunta de negócio pede para expor.
    valor_por_cliente_bruto: dict[int, float] = defaultdict(float)
    for v in Venda.objects.only("cliente_id", "valor_venda").all():
        valor_por_cliente_bruto[v.cliente_id] += v.valor_venda

    valor_por_cliente_tratado: dict[int, float] = defaultdict(float)
    for cid, valor in valor_por_cliente_bruto.items():
        canon = canonico_por_id.get(cid, cid)
        valor_por_cliente_tratado[canon] += valor

    receita_total = sum(valor_por_cliente_bruto.values())
    n_compradores_bruto = len(valor_por_cliente_bruto)
    n_compradores_tratado = len(valor_por_cliente_tratado)

    return ImpactoDuplicidade(
        grupos_duplicados=grupos,
        registros_duplicados=registros_duplicados,
        clientes_unicos_bruto=len(clientes),
        clientes_unicos_tratado=len(clientes) - registros_duplicados,
        ticket_medio_bruto=(receita_total / n_compradores_bruto) if n_compradores_bruto else 0.0,
        ticket_medio_tratado=(receita_total / n_compradores_tratado)
        if n_compradores_tratado
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
