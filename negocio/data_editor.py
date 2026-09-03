"""
Edição de registros na tela Dados -- restrita às duas tabelas sem regra de negócio
associada: clientes e empreendimentos.

unidades/vendas ficam de fora de propósito: editar unidades.status ou vendas.status_venda
direto aqui bypassaria venda_esta_ativa()/UNIDADE_INDISPONIVEL (negocio/normalize.py) e o
resto da aplicação que confia nelas -- a forma correta de mudar o estado dessas duas
tabelas já existe (Nova venda / Registrar distrato, negocio/services.py), com a regra de
negócio certa aplicada. obra_andamento/financeiro_mensal também ficam de fora: alimentam
achados documentados (ver README, "Decisões de modelagem") que dependem dos números como
vieram da base.

As FKs desta base não têm constraint no banco (db_constraint=False em models.py, pensado
pra apontar pras tabelas exatamente como entregues) -- por isso excluir um cliente/
empreendimento com linhas vinculadas deixaria unidades.empreendimento_id ou
vendas.cliente_id órfãos em vez de dar erro. _guard_* abaixo é essa checagem que o banco
não faz sozinho.
"""

from dataclasses import dataclass
from typing import Callable

from django import forms as django_forms
from django.db.models import Model

from .forms import ClienteForm, EmpreendimentoForm
from .models import Cliente, Empreendimento, FinanceiroMensal, ObraAndamento, Unidade, Venda


@dataclass
class DefinicaoEdicao:
    model: type[Model]
    form_class: type[django_forms.ModelForm]
    guard_exclusao: Callable[[Model], str | None]  # mensagem de erro, ou None se pode excluir


def _guard_cliente(cliente: Cliente) -> str | None:
    total = Venda.objects.filter(cliente=cliente).count()
    if total:
        return (
            f'Não é possível excluir "{cliente.nome}": há {total} venda(s) vinculada(s) '
            "a este cliente."
        )
    return None


def _guard_empreendimento(empreendimento: Empreendimento) -> str | None:
    vinculos = []
    n_unidades = Unidade.objects.filter(empreendimento=empreendimento).count()
    if n_unidades:
        vinculos.append(f"{n_unidades} unidade(s)")
    n_obra = ObraAndamento.objects.filter(empreendimento=empreendimento).count()
    if n_obra:
        vinculos.append(f"{n_obra} medição(ões) de obra")
    n_fin = FinanceiroMensal.objects.filter(empreendimento=empreendimento).count()
    if n_fin:
        vinculos.append(f"{n_fin} linha(s) financeira(s)")
    if vinculos:
        return (
            f'Não é possível excluir "{empreendimento.nome}": há '
            f"{', '.join(vinculos)} vinculado(s) a ele."
        )
    return None


TABELAS_EDITAVEIS: dict[str, DefinicaoEdicao] = {
    "clientes": DefinicaoEdicao(Cliente, ClienteForm, _guard_cliente),
    "empreendimentos": DefinicaoEdicao(Empreendimento, EmpreendimentoForm, _guard_empreendimento),
}
