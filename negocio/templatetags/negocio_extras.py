import os

from django.conf import settings
from django.templatetags.static import static
from django import template

from negocio.analytics import nome_com_localizacao

register = template.Library()


@register.filter
def com_localizacao(cliente):
    return nome_com_localizacao(cliente)


@register.filter
def dict_get(d, chave):
    """Busca `chave` num dict a partir do template (ex.: tabela.filtros_valores) -- o
    Django só resolve dict.chave quando a chave é literal, não uma variável."""
    if not d:
        return ""
    return d.get(chave, "")


@register.filter
def concat(a, b):
    """Concatena duas strings no template (ex.: pra montar "{{ chave }}_min")."""
    return f"{a}{b}"


@register.filter
def lookup(chave, d):
    """Como dict_get, mas com os argumentos invertidos -- útil quando a chave já vem de
    uma cadeia de filtros (ex.: {{ f.chave|concat:"_min"|lookup:valores }})."""
    if not d:
        return ""
    return d.get(chave, "")


@register.simple_tag
def static_v(path):
    """Like {% static %}, but appends ?v=<mtime> so browsers never serve a stale cached
    copy after a static file changes -- plain {% static %} URLs are stable, so a browser
    that already cached style.css keeps using the old version until this forces a new
    URL. No build step in this project generates hashed filenames, so this is the
    simplest fix that doesn't require one."""
    url = static(path)
    try:
        mtime = int(os.path.getmtime(settings.BASE_DIR / "static" / path))
    except OSError:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}v={mtime}"
