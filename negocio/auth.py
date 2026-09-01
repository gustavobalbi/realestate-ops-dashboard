"""
Minimal session-based authentication against the existing `usuarios` table.

Deliberately NOT using django.contrib.auth: the brief asks for a simple login built
directly from the `usuarios` table already in the base, explicitly says production-grade
hashing isn't required, and asks that the limitation be documented instead (see README).

What this does: passwords are hashed with salted SHA-256 (negocio.auth.hash_password) and
compared to `usuarios.senha_hash`. This is NOT suitable for production -- there's no
per-user salt rotation, no rate limiting/lockout, and SHA-256 is fast to brute-force
compared to a real password hash (bcrypt/argon2). It is enough to demonstrate the flow
end to end, which is what this test asks for.
"""

import functools
import hashlib

from django.shortcuts import redirect
from django.urls import reverse

from .models import Usuario

# Fixed application-wide salt. In a production system this would be per-user and
# generated with a proper KDF (bcrypt/argon2/scrypt) instead of being hardcoded.
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
    """Attaches request.usuario (or None) once per request."""

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
