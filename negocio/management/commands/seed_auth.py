"""
One-off setup step: replace the `trocar_no_setup` placeholder in usuarios.senha_hash
with an actual salted SHA-256 hash of a default password, so the login screen works.

The default password is the same string the base ships with ("trocar_no_setup"), kept as
the login password for every seed user for demo purposes. Run again with --password to
set a different default for every seed user still on the placeholder.
"""

from django.core.management.base import BaseCommand

from negocio.auth import hash_password
from negocio.models import Usuario

PLACEHOLDER = "trocar_no_setup"


class Command(BaseCommand):
    help = "Hashes the placeholder password for seed users in the usuarios table."

    def add_arguments(self, parser):
        parser.add_argument("--password", default=PLACEHOLDER)

    def handle(self, *args, **options):
        password = options["password"]
        pending = Usuario.objects.filter(senha_hash=PLACEHOLDER)
        count = 0
        for usuario in pending:
            usuario.senha_hash = hash_password(password)
            usuario.save(update_fields=["senha_hash"])
            count += 1
        if count:
            self.stdout.write(
                self.style.SUCCESS(
                    f"{count} usuário(s) atualizados. Senha de acesso: '{password}'."
                )
            )
        else:
            self.stdout.write("Nenhum usuário com placeholder pendente encontrado.")
