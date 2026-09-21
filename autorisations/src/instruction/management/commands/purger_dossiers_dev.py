import json
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from instruction.management.commands.inventorier_purge_dev import (
    Command as CommandeInventaire,
)


class Command(BaseCommand):
    help = (
        "Orchestre la purge DEV : sauvegarde, manifeste à 12 mois et exécution "
        "d'un lot plafonné. Simulation d'inventaire par défaut."
    )

    def add_arguments(self, parser):
        parser.add_argument("--months", type=int, default=12)
        parser.add_argument("--limite", type=int, default=25)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--confirmation",
            help="Confirmation obligatoire PURGER-DEV-<nombre>M.",
        )

    def handle(self, *args, **options):
        CommandeInventaire()._verifier_cible_developpement()
        mois = options["months"]
        limite = options["limite"]
        if mois < 1:
            raise CommandError("--months doit être supérieur ou égal à 1.")
        if limite < 1 or limite > 25:
            raise CommandError("--limite doit être compris entre 1 et 25.")

        if not options["execute"]:
            call_command(
                "inventorier_purge_dev",
                months=mois,
                scan_nas=True,
                rapport_csv=True,
                stdout=self.stdout,
                stderr=self.stderr,
            )
            self.stdout.write(self.style.WARNING(
                "Orchestration en simulation : aucune sauvegarde nouvelle, "
                "aucun manifeste et aucune purge."
            ))
            return

        confirmation = f"PURGER-DEV-{mois}M"
        if options.get("confirmation") != confirmation:
            raise CommandError(f"Confirmation {confirmation} requise.")

        dossier_lots = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve() / "lots"
        avant = set(dossier_lots.glob(f"lot_purge_{mois}mois_*.json")) \
            if dossier_lots.is_dir() else set()

        call_command("sauvegarder_bdd_dev", stdout=self.stdout, stderr=self.stderr)
        try:
            call_command(
                "inventorier_purge_dev",
                months=mois,
                scan_nas=True,
                rapport_csv=True,
                manifeste=True,
                stdout=self.stdout,
                stderr=self.stderr,
            )
        except CommandError as exc:
            if "Aucun candidat" in str(exc):
                self.stdout.write(self.style.SUCCESS(
                    "Aucun dossier éligible : sauvegarde conservée, aucune purge."
                ))
                return
            raise

        apres = set(dossier_lots.glob(f"lot_purge_{mois}mois_*.json"))
        nouveaux = list(apres - avant)
        if len(nouveaux) != 1:
            raise CommandError(
                "Impossible d'identifier sans ambiguïté le nouveau manifeste."
            )
        manifeste = nouveaux[0]
        contenu = json.loads(manifeste.read_text(encoding="utf-8"))
        cles = [unite["cle"] for unite in contenu["unites"][:limite]]
        if not cles:
            self.stdout.write(self.style.SUCCESS("Aucune unité sûre à purger."))
            return
        confirmation_lot = f"EXECUTER-{contenu['selection_sha256'][:12]}"
        call_command(
            "executer_purge_dev",
            manifeste=str(manifeste),
            cles=cles,
            limite=limite,
            execute=True,
            confirmation=confirmation_lot,
            stdout=self.stdout,
            stderr=self.stderr,
        )
