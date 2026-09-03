"""
Autenticação simples por sessão contra a tabela `usuarios` já existente.

Deliberadamente SEM django.contrib.auth: o briefing pede um login simples construído
direto sobre a tabela `usuarios` já na base, diz explicitamente que hash de nível
produção não é necessário, e pede que a limitação seja documentada em vez disso (ver
README).

Como funciona: senhas são hasheadas com SHA-256 + salt (negocio.auth.hash_password) e
comparadas com `usuarios.senha_hash`. Isso NÃO é adequado para produção -- não há
rotação de salt por usuário, nem rate limiting/bloqueio, e SHA-256 é rápido de quebrar
por força bruta comparado a um hash de senha de verdade (bcrypt/argon2). É suficiente
para demonstrar o fluxo ponta a ponta, que é o que este teste pede.
"""

import functools
import hashlib

from django.shortcuts import redirect
from django.urls import reverse

from .models import Usuario

# Salt fixo, global pra aplicação inteira. Num sistema de produção seria por usuário e
# gerado com um KDF de verdade (bcrypt/argon2/scrypt) em vez de fixo no código.
_SALT = "cambara-teste-tecnico"


def hash_password(raw_password: str) -> str:
    return hashlib.sha256((_SALT + raw_password).encode("utf-8")).hexdigest()


def authenticate(email: str, raw_password: str) -> Usuario | None:
    try:
        usuario = Usuario.objects.get(email__iexact=email.strip())
    except Usuario.DoesNotExist:
        return None
    if usuario.senha_hash == hash_password(raw_password):
        return usuario
    return None


def login(request, usuario: Usuario) -> None:
    request.session["usuario_id"] = usuario.id
    request.session.cycle_key()


def logout(request) -> None:
    request.session.flush()


def get_current_user(request) -> Usuario | None:
    usuario_id = request.session.get("usuario_id")
    if not usuario_id:
        return None
    try:
        return Usuario.objects.get(id=usuario_id)
    except Usuario.DoesNotExist:
        return None


class CurrentUserMiddleware:
    """Anexa request.usuario (ou None) uma vez por requisição."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.usuario = get_current_user(request)
        return self.get_response(request)


def current_user_context(request):
    return {"usuario_logado": getattr(request, "usuario", None)}


def login_required(view_func):
    @functools.wraps(view_func)
    def wrapped(request, *args, **kwargs):
        if request.usuario is None:
            return redirect(f"{reverse('login')}?next={request.path}")
        return view_func(request, *args, **kwargs)

    return wrapped
