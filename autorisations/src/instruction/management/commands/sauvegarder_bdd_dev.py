import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.utils import timezone


class Command(BaseCommand):
    help = (
        "Crée une sauvegarde PostgreSQL complète et vérifiable de la BDD DEV "
        "avant une purge. Cette commande ne modifie aucune donnée."
    )

    def handle(self, *args, **options):
        self._verifier_cible_developpement()

        executable = self._trouver_pg_dump()
        if not executable:
            raise CommandError(
                "pg_dump est introuvable. Installez les outils client PostgreSQL "
                "ou renseignez PG_DUMP_PATH dans .env.dev."
            )
        pg_restore = self._trouver_pg_restore(executable)
        if not pg_restore:
            raise CommandError(
                "pg_restore est introuvable. Installez les outils client PostgreSQL "
                "ou renseignez PG_RESTORE_PATH dans .env.dev."
            )

        configuration = connections["default"].settings_dict
        horodatage = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        dossier = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve() / "sauvegardes"
        dossier.mkdir(parents=True, exist_ok=True)
        archive = dossier / f"agida_dev_avant_purge_{horodatage}.dump"

        commande = [
            executable,
            "--format=custom",
            "--compress=9",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(archive),
        ]
        for option, valeur in (
            ("--host", configuration.get("HOST")),
            ("--port", configuration.get("PORT")),
            ("--username", configuration.get("USER")),
        ):
            if valeur:
                commande.extend((option, str(valeur)))
        commande.append(str(configuration["NAME"]))

        environnement = os.environ.copy()
        if configuration.get("PASSWORD"):
            environnement["PGPASSWORD"] = str(configuration["PASSWORD"])

        resultat = subprocess.run(
            commande,
            env=environnement,
            capture_output=True,
            text=True,
            check=False,
        )
        environnement.pop("PGPASSWORD", None)
        if resultat.returncode != 0:
            archive.unlink(missing_ok=True)
            detail = (resultat.stderr or resultat.stdout).strip()
            raise CommandError(f"Échec de pg_dump : {detail}")

        verification = subprocess.run(
            [pg_restore, "--list", str(archive)],
            capture_output=True,
            text=True,
            check=False,
        )
        if verification.returncode != 0 or not verification.stdout.strip():
            archive.unlink(missing_ok=True)
            detail = (verification.stderr or verification.stdout).strip()
            raise CommandError(f"Archive créée mais illisible par pg_restore : {detail}")

        empreinte = self._sha256(archive)
        fichier_empreinte = archive.with_suffix(".dump.sha256")
        fichier_empreinte.write_text(
            f"{empreinte}  {archive.name}\n",
            encoding="utf-8",
        )
        metadata = archive.with_suffix(".dump.json")
        metadata.write_text(
            json.dumps(
                {
                    "cree_le": timezone.now().isoformat(),
                    "environnement": "dev",
                    "base": configuration["NAME"],
                    "archive": archive.name,
                    "taille_octets": archive.stat().st_size,
                    "sha256": empreinte,
                    "verification_pg_restore": True,
                    "lecture_seule": True,
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        self.stdout.write(self.style.SUCCESS("Sauvegarde BDD DEV créée et vérifiée."))
        self.stdout.write(f"Archive : {archive}")
        self.stdout.write(f"SHA-256 : {empreinte}")
        self.stdout.write("Aucune donnée BDD et aucun fichier NAS n'ont été modifiés.")

    @staticmethod
    def _sha256(chemin):
        empreinte = hashlib.sha256()
        with chemin.open("rb") as fichier:
            for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
                empreinte.update(bloc)
        return empreinte.hexdigest()

    @staticmethod
    def _trouver_pg_dump():
        chemin_configure = os.environ.get("PG_DUMP_PATH")
        if chemin_configure:
            chemin = Path(chemin_configure).expanduser()
            if chemin.is_file():
                return str(chemin)
            raise CommandError(
                f"Le fichier défini par PG_DUMP_PATH est introuvable : {chemin}"
            )

        executable = shutil.which("pg_dump")
        if executable:
            return executable

        if os.name == "nt":
            chemins_connus = [
                Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
                / "pgAdmin 4"
                / "runtime"
                / "pg_dump.exe",
                Path(os.environ.get("LOCALAPPDATA", ""))
                / "Programs"
                / "pgAdmin 4"
                / "runtime"
                / "pg_dump.exe",
            ]
            for chemin in chemins_connus:
                if chemin.is_file():
                    return str(chemin)

            dossier_postgresql = Path(
                os.environ.get("ProgramFiles", r"C:\Program Files")
            ) / "PostgreSQL"
            if dossier_postgresql.is_dir():
                versions = sorted(dossier_postgresql.iterdir(), reverse=True)
                for version in versions:
                    chemin = version / "bin" / "pg_dump.exe"
                    if chemin.is_file():
                        return str(chemin)

        return None

    @staticmethod
    def _trouver_pg_restore(pg_dump):
        chemin_configure = os.environ.get("PG_RESTORE_PATH")
        if chemin_configure:
            chemin = Path(chemin_configure).expanduser()
            if chemin.is_file():
                return str(chemin)
            raise CommandError(
                f"Le fichier défini par PG_RESTORE_PATH est introuvable : {chemin}"
            )

        executable = shutil.which("pg_restore")
        if executable:
            return executable

        nom = "pg_restore.exe" if os.name == "nt" else "pg_restore"
        voisin = Path(pg_dump).resolve().parent / nom
        if voisin.is_file():
            return str(voisin)
        return None

    @staticmethod
    def _verifier_cible_developpement():
        if settings.ENVIRONMENT != "dev":
            raise CommandError(
                "Cette commande est réservée à l'environnement de développement."
            )
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "SELECT environnement "
                    "FROM maintenance.environnement_agida WHERE id = true"
                )
                ligne = cursor.fetchone()
        except Exception as exc:
            raise CommandError(
                "Marqueur de la BDD de développement absent ou inaccessible."
            ) from exc
        if not ligne or ligne[0] != "dev":
            raise CommandError(
                "La BDD cible n'est pas marquée comme environnement 'dev'."
            )
