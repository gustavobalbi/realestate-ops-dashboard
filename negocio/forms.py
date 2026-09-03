from django import forms

from .models import Cliente, Empreendimento
from .normalize import CANONICAL_MODELO_NEGOCIO


class DateInputISO(forms.DateInput):
    """<input type="date"> só aceita o valor pré-preenchido no formato ISO (AAAA-MM-DD) --
    o DateInput padrão do Django usa o formato localizado (pt-br: DD/MM/AAAA), que o
    navegador rejeita como valor inválido pra esse tipo de input (o campo simplesmente
    aparece vazio e a validação nativa do HTML5 bloqueia o envio do formulário, sem
    nenhum erro visível). Achado ao testar o formulário de edição da tela Dados; o mesmo
    problema já existia (silencioso) no formulário de Nova venda."""

    def __init__(self, attrs=None):
        super().__init__(attrs={"type": "date", **(attrs or {})}, format="%Y-%m-%d")


FORMAS_PAGAMENTO = [
    ("À vista", "À vista"),
    ("Financiamento", "Financiamento"),
    ("Parcelado Direto", "Parcelado Direto"),
]

UF_CHOICES = [(uf, uf) for uf in [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]]
PERFIL_CLIENTE_CHOICES = [("Morador", "Morador"), ("Investidor", "Investidor"),
                           ("Institucional", "Institucional")]
TIPO_EMPREENDIMENTO_CHOICES = [("Residencial", "Residencial"), ("Comercial", "Comercial"),
                                ("Misto", "Misto")]
STATUS_EMPREENDIMENTO_CHOICES = [("Lançamento", "Lançamento"), ("Em obras", "Em obras"),
                                  ("Concluído", "Concluído"), ("Suspenso", "Suspenso")]
# Grafia canônica só -- salvar por este form sempre escreve a grafia limpa, mesmo editando
# uma linha que veio com uma das 9 variantes históricas (ver negocio/normalize.py).
MODELO_NEGOCIO_CHOICES = [(v, v) for v in CANONICAL_MODELO_NEGOCIO.values()]


def _com_vazio(choices):
    return [("", "---")] + choices


class ClienteForm(forms.ModelForm):
    """Edição/criação na tela Dados -- clientes não tem regra de negócio associada (ver
    negocio/data_editor.py), então edição/exclusão livre aqui é segura."""

    class Meta:
        model = Cliente
        fields = ["nome", "cidade", "uf", "perfil", "data_cadastro", "email"]
        # As colunas do banco são TEXT (ver models.py), então o ModelForm usaria <textarea>
        # por padrão pra todas -- força <input> nos campos que são texto curto de verdade.
        widgets = {
            "nome": forms.TextInput(),
            "cidade": forms.TextInput(),
            "email": forms.EmailInput(),
            "data_cadastro": DateInputISO(),
            "uf": forms.Select(choices=_com_vazio(UF_CHOICES)),
            "perfil": forms.Select(choices=_com_vazio(PERFIL_CLIENTE_CHOICES)),
        }


class EmpreendimentoForm(forms.ModelForm):
    """Edição/criação na tela Dados. status/tipo/modelo_negocio aqui são só informativos
    (nada no app valida/deriva a partir deles como faz com unidades.status/vendas.status_venda)
    -- por isso é seguro editar livremente, diferente daquelas duas colunas."""

    class Meta:
        model = Empreendimento
        fields = ["nome", "cidade", "uf", "tipo", "modelo_negocio", "vgv_estimado",
                  "data_lancamento", "status", "observacoes"]
        # Idem ClienteForm -- só observacoes é texto longo de verdade.
        widgets = {
            "nome": forms.TextInput(),
            "cidade": forms.TextInput(),
            "data_lancamento": DateInputISO(),
            "uf": forms.Select(choices=_com_vazio(UF_CHOICES)),
            "tipo": forms.Select(choices=_com_vazio(TIPO_EMPREENDIMENTO_CHOICES)),
            "modelo_negocio": forms.Select(choices=_com_vazio(MODELO_NEGOCIO_CHOICES)),
            "status": forms.Select(choices=_com_vazio(STATUS_EMPREENDIMENTO_CHOICES)),
            "observacoes": forms.Textarea(attrs={"rows": 3}),
        }


class LoginForm(forms.Form):
    email = forms.EmailField(label="E-mail")
    senha = forms.CharField(label="Senha", widget=forms.PasswordInput)


class NovaVendaForm(forms.Form):
    empreendimento_id = forms.IntegerField(widget=forms.HiddenInput, required=False)
    unidade_id = forms.IntegerField(label="Unidade disponível")
    cliente_id = forms.IntegerField(required=False, widget=forms.HiddenInput)
    cliente_busca = forms.CharField(label="Cliente existente", required=False)
    cliente_novo_nome = forms.CharField(label="Nome do novo cliente", required=False)
    cliente_novo_email = forms.EmailField(label="E-mail", required=False)
    cliente_novo_cidade = forms.CharField(label="Cidade", required=False)
    cliente_novo_uf = forms.CharField(label="UF", required=False, max_length=2)
    cliente_novo_perfil = forms.CharField(label="Perfil", required=False)
    valor_venda = forms.FloatField(label="Valor da venda (R$)", min_value=0)
    forma_pagamento = forms.ChoiceField(label="Forma de pagamento", choices=FORMAS_PAGAMENTO)
    data_venda = forms.DateField(label="Data da venda", widget=DateInputISO())

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("cliente_id") and not cleaned.get("cliente_novo_nome"):
            raise forms.ValidationError(
                "Selecione um cliente existente ou informe o nome de um novo cliente."
            )
        return cleaned


class PerguntaForm(forms.Form):
    pergunta = forms.CharField(
        label="Pergunta",
        widget=forms.Textarea(attrs={"rows": 2, "placeholder": "Ex.: Qual empreendimento tem maior risco de estouro de custo?"}),
    )
