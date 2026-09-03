"""
Modelos que espelham as tabelas já presentes em data_cambara.sqlite3.

Todos os modelos são `managed = False`: o Django nunca cria, altera nem apaga essas
tabelas. Isso permite que a aplicação leia e escreva na base exatamente como foi
entregue, sem redesenhar o schema (conforme pedido no briefing). Normalização de
qualidade de dados (grafia de status, clientes duplicados etc.) é feita em Python na
camada de leitura -- ver negocio/normalize.py e negocio/analytics.py -- em vez de mutar
linhas históricas.
"""

from django.db import models


class Empreendimento(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.TextField()
    cidade = models.TextField()
    uf = models.TextField()
    tipo = models.TextField()
    modelo_negocio = models.TextField()
    vgv_estimado = models.FloatField(null=True)
    data_lancamento = models.DateField()
    status = models.TextField()
    observacoes = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "empreendimentos"

    def __str__(self):
        return self.nome


class Unidade(models.Model):
    id = models.AutoField(primary_key=True)
    empreendimento = models.ForeignKey(
        Empreendimento,
        db_column="empreendimento_id",
        on_delete=models.DO_NOTHING,
        related_name="unidades",
        db_constraint=False,
    )
    identificador = models.TextField()
    tipo = models.TextField()
    area_privativa_m2 = models.FloatField()
    valor_tabela = models.FloatField()
    status = models.TextField()

    class Meta:
        managed = False
        db_table = "unidades"

    def __str__(self):
        return f"{self.identificador} ({self.empreendimento_id})"


class Cliente(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.TextField()
    cidade = models.TextField(null=True, blank=True)
    uf = models.TextField(null=True, blank=True)
    perfil = models.TextField(null=True, blank=True)
    data_cadastro = models.DateField()
    email = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "clientes"

    def __str__(self):
        return self.nome


class Venda(models.Model):
    id = models.AutoField(primary_key=True)
    unidade = models.ForeignKey(
        Unidade,
        db_column="unidade_id",
        on_delete=models.DO_NOTHING,
        related_name="vendas",
        db_constraint=False,
    )
    cliente = models.ForeignKey(
        Cliente,
        db_column="cliente_id",
        on_delete=models.DO_NOTHING,
        related_name="vendas",
        db_constraint=False,
    )
    data_venda = models.DateField()
    valor_venda = models.FloatField()
    forma_pagamento = models.TextField()
    status_venda = models.TextField()
    data_distrato = models.DateField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "vendas"

    def __str__(self):
        return f"Venda #{self.id}"


class ObraAndamento(models.Model):
    id = models.AutoField(primary_key=True)
    empreendimento = models.ForeignKey(
        Empreendimento,
        db_column="empreendimento_id",
        on_delete=models.DO_NOTHING,
        related_name="medicoes",
        db_constraint=False,
    )
    mes_referencia = models.DateField()
    percentual_conclusao = models.FloatField()
    custo_orcado_mes = models.FloatField()
    custo_realizado_mes = models.FloatField()
    observacoes = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = "obra_andamento"


class FinanceiroMensal(models.Model):
    id = models.AutoField(primary_key=True)
    empreendimento = models.ForeignKey(
        Empreendimento,
        db_column="empreendimento_id",
        on_delete=models.DO_NOTHING,
        related_name="financeiro",
        db_constraint=False,
    )
    mes_referencia = models.DateField()
    receita_reconhecida = models.FloatField()
    custo_incorrido = models.FloatField()
    despesas_corporativas_rat = models.FloatField()
    resultado_reportado = models.FloatField()

    class Meta:
        managed = False
        db_table = "financeiro_mensal"


class Usuario(models.Model):
    id = models.AutoField(primary_key=True)
    nome = models.TextField()
    email = models.TextField()
    papel = models.TextField()
    senha_hash = models.TextField()

    class Meta:
        managed = False
        db_table = "usuarios"

    def __str__(self):
        return self.nome
