"""
Passo de setup pontual: define o `usuarios.senha_hash` de cada linha como o hash
SHA-256 + salt de uma senha de demonstração por usuário -- a primeira palavra do próprio
`nome` + "123" (ex.: "Diretoria Cambará" -> "Diretoria123"). Substitui a senha
placeholder única e compartilhada ("trocar_no_setup") que vem na base, então cada
usuário seed ganha um login próprio e memorável para a demonstração.

Seguro de rodar de novo: sempre recalcula e sobrescreve senha_hash de toda linha em
`usuarios`, então rodar duas vezes não muda nada (mesmo nome de entrada -> mesma senha).
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
