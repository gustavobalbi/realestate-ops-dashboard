from django import template

from negocio.analytics import nome_com_localizacao

register = template.Library()


@register.filter
def com_localizacao(cliente):
    return nome_com_localizacao(cliente)
