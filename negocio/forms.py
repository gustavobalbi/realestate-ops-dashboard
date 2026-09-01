from django import forms

FORMAS_PAGAMENTO = [
    ("À vista", "À vista"),
    ("Financiamento", "Financiamento"),
    ("Parcelado Direto", "Parcelado Direto"),
]


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
    data_venda = forms.DateField(label="Data da venda", widget=forms.DateInput(attrs={"type": "date"}))

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
