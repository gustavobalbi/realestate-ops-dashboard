import os

from django.conf import settings
from django.templatetags.static import static
from django import template

from negocio.analytics import nome_com_localizacao

register = template.Library()


@register.filter
def com_localizacao(cliente):
    return nome_com_localizacao(cliente)


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
