from datetime import datetime
import ntpath
import os
from pathlib import Path
import platform
import re
import shutil

from dateutil.relativedelta import relativedelta
import smbclient
import smbclient.shutil as smb_shutil
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from instruction.management.commands.inventorier_purge_dev import (
    Command as CommandeInventaire,
)


FORMAT_LOT = re.compile(r"^\d{8}_\d{6}(?:_\d{6})?$")


class Command(BaseCommand):
    help = (
        "Inventorie ou supprime les éléments de purge DEV conservés depuis "
        "plus de 30 jours. Simulation par défaut."
    )

    def add_arguments(self, parser):
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--confirmation",
            help="Confirmation obligatoire au format NETTOYER-<nombre de jours>J.",
        )

    def handle(self, *args, **options):
        CommandeInventaire()._verifier_cible_developpement()
        jours = options["days"]
        if jours < 1:
            raise CommandError("--days doit être supérieur ou égal à 1.")
        limite = timezone.now() - relativedelta(days=jours)

        lots_nas = self._lots_nas_expires(limite)
        fichiers_locaux = self._fichiers_locaux_expires(limite)
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Nettoyage réel" if options["execute"] else "Simulation du nettoyage"
        ))
        self.stdout.write(f"Éléments antérieurs au : {limite:%d/%m/%Y %H:%M}")
        self.stdout.write(f"Lots NAS expirés : {len(lots_nas)}")
        for chemin in lots_nas:
            self.stdout.write(f"  NAS : {chemin}")
        self.stdout.write(f"Fichiers locaux expirés : {len(fichiers_locaux)}")
        for chemin in fichiers_locaux:
            self.stdout.write(f"  Archive : {chemin}")

        if not options["execute"]:
            self.stdout.write(self.style.WARNING(
                "SIMULATION uniquement. Ajoutez --execute "
                f"--confirmation NETTOYER-{jours}J pour supprimer ces éléments."
            ))
            return
        if options.get("confirmation") != f"NETTOYER-{jours}J":
            raise CommandError(f"Confirmation NETTOYER-{jours}J requise.")

        for chemin in lots_nas:
            self._supprimer_repertoire_nas(chemin)
        for chemin in fichiers_locaux:
            chemin.unlink()
        self.stdout.write(self.style.SUCCESS(
            f"Nettoyage terminé : {len(lots_nas)} lot(s) NAS et "
            f"{len(fichiers_locaux)} fichier(s) local(aux) supprimés."
        ))

    def _lots_nas_expires(self, limite):
        racine = os.environ.get("NAS_ROOT")
        if not racine:
            raise CommandError("NAS_ROOT n'est pas configuré.")
        unc = racine.startswith("\\\\")
        if unc:
            racine = ntpath.normpath(racine)
        joindre = ntpath.join if unc else os.path.join
        corbeille = joindre(racine, "_corbeille_agida")
        if not self._existe(corbeille):
            return []

        expires = []
        for nom in self._lister_repertoires(corbeille):
            # Seuls les lots créés par nos commandes peuvent être supprimés.
            if not FORMAT_LOT.fullmatch(nom):
                continue
            date_lot = self._date_lot(nom)
            if date_lot < limite:
                expires.append(joindre(corbeille, nom))
        return sorted(expires)

    @staticmethod
    def _fichiers_locaux_expires(limite):
        racine = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve()
        if not racine.is_dir():
            return []
        expires = []
        for sous_dossier in ("sauvegardes", "rapports", "lots", "executions"):
            dossier = racine / sous_dossier
            if not dossier.is_dir():
                continue
            for chemin in dossier.iterdir():
                if not chemin.is_file():
                    continue
                modification = datetime.fromtimestamp(
                    chemin.stat().st_mtime,
                    tz=timezone.get_current_timezone(),
                )
                if modification < limite:
                    expires.append(chemin)
        return sorted(expires)

    @staticmethod
    def _date_lot(nom):
        valeur = nom[:15]
        date_naive = datetime.strptime(valeur, "%Y%m%d_%H%M%S")
        return timezone.make_aware(date_naive, timezone.get_current_timezone())

    @staticmethod
    def _existe(chemin):
        if platform.system() == "Windows" or chemin.startswith("\\\\"):
            return smbclient.path.exists(chemin)
        return os.path.exists(chemin)

    @staticmethod
    def _lister_repertoires(chemin):
        if platform.system() == "Windows" or chemin.startswith("\\\\"):
            return sorted(
                entree.name for entree in smbclient.scandir(chemin)
                if entree.is_dir()
            )
        return sorted(
            entree.name for entree in os.scandir(chemin) if entree.is_dir()
        )

    @staticmethod
    def _supprimer_repertoire_nas(chemin):
        nom = ntpath.basename(chemin) if chemin.startswith("\\\\") else os.path.basename(chemin)
        if not FORMAT_LOT.fullmatch(nom):
            raise CommandError(f"Refus de supprimer un chemin NAS non reconnu : {chemin}")
        if platform.system() == "Windows" or chemin.startswith("\\\\"):
            smb_shutil.rmtree(chemin)
        else:
            shutil.rmtree(chemin)
