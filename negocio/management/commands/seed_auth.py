"""
One-off setup step: set every usuarios.senha_hash to a salted SHA-256 hash of a
per-user demo password -- the first word of the user's own `nome` + "123" (ex.: "Diretoria
Cambará" -> "Diretoria123"). Replaces the single shared placeholder password
("trocar_no_setup") that ships with the base, so each seed user gets a distinct,
memorable login for the demo.

Safe to re-run: it always recomputes and overwrites senha_hash for every row in
`usuarios`, so running it twice is a no-op (same input nome -> same password).
"""

from django.core.management.base import BaseCommand

from negocio.auth import hash_password
from negocio.models import Usuario


def senha_padrao(nome: str) -> str:
    primeira_palavra = nome.strip().split()[0]
    return f"{primeira_palavra}123"


class Command(BaseCommand):
    help = "Define a senha de cada usuário como a primeira palavra do nome + '123'."

    def handle(self, *args, **options):
        usuarios = list(Usuario.objects.all())
        if not usuarios:
            self.stdout.write("Nenhum usuário encontrado na tabela usuarios.")
            return

        for usuario in usuarios:
            senha = senha_padrao(usuario.nome)
            usuario.senha_hash = hash_password(senha)
            usuario.save(update_fields=["senha_hash"])
            self.stdout.write(f"{usuario.email} -> senha '{senha}'")

        self.stdout.write(self.style.SUCCESS(f"{len(usuarios)} usuário(s) atualizados."))
