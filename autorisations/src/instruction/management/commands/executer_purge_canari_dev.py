import json
from io import StringIO
import ntpath
import os
from pathlib import Path
import platform

import smbclient
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from autorisations.models.models_documents import (
    Document,
    DossierDocument,
    DossierRelecteurDocument,
    MessageDocument,
)
from autorisations.models.models_instruction import (
    Demande,
    DemandeChamp,
    Dossier,
    DossierChamp,
    Message,
)
from autorisations.models.models_utilisateurs import DossierRelecteur, EmailOutbox


class Command(BaseCommand):
    help = (
        "Met en corbeille le NAS puis supprime en BDD une seule unité DN canari. "
        "Sans --execute, la commande reste en simulation."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifeste", required=True)
        parser.add_argument("--numero", required=True)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--confirmation",
            help="Confirmation obligatoire au format SUPPRIMER-<numero>.",
        )

    def handle(self, *args, **options):
        manifeste = str(Path(options["manifeste"]).expanduser().resolve())
        numero = str(options["numero"]).strip()

        # Rejoue tous les contrôles d'intégrité, de sauvegarde, de BDD et de NAS.
        call_command(
            "verifier_purge_canari_dev",
            manifeste=manifeste,
            numero=numero,
            stdout=self.stdout,
            stderr=self.stderr,
        )

        unite = self._unite(manifeste, numero)
        source, destination = self._chemins_nas(unite, numero)
        self.stdout.write("")
        titre = "Plan d'exécution du canari" if options["execute"] else "Simulation du canari"
        self.stdout.write(self.style.MIGRATE_HEADING(titre))
        self.stdout.write(f"Source NAS : {source}")
        self.stdout.write(f"Corbeille NAS : {destination}")
        self.stdout.write(f"Dossier DN supprimé en BDD : {numero}")
        self.stdout.write(f"Documents BDD concernés : {unite['documents']}")

        if not options["execute"]:
            self.stdout.write(
                self.style.WARNING(
                    "SIMULATION uniquement. Relancez avec --execute et "
                    f"--confirmation SUPPRIMER-{numero} après contrôle."
                )
            )
            return
        if options.get("confirmation") != f"SUPPRIMER-{numero}":
            raise CommandError(
                f"Confirmation incorrecte : --confirmation SUPPRIMER-{numero} est requis."
            )

        journal = self._creer_journal(manifeste, numero, source, destination)
        deplace = False
        try:
            with transaction.atomic(using="default"):
                dossier = Dossier.objects.using("default").select_for_update().get(
                    pk=unite["ids_dn"][0], numero=int(numero)
                )
                # Contrôle final après verrouillage du dossier.
                call_command(
                    "verifier_purge_canari_dev",
                    manifeste=manifeste,
                    numero=numero,
                    verbosity=0,
                    stdout=StringIO(),
                    stderr=StringIO(),
                )
                ids_documents = self._ids_documents(dossier.id)
                self._deplacer(source, destination)
                deplace = True
                self._maj_journal(journal, "nas_en_corbeille")

                dossier.delete(using="default")
                if ids_documents:
                    Document.objects.using("default").filter(
                        id__in=ids_documents
                    ).delete()

            self._maj_journal(journal, "termine")
        except Exception as exc:
            erreur_restauration = ""
            if deplace:
                try:
                    self._deplacer(destination, source)
                except Exception as restauration_exc:
                    erreur_restauration = str(restauration_exc)
            self._maj_journal(
                journal,
                "echec",
                erreur=str(exc),
                erreur_restauration_nas=erreur_restauration,
            )
            if erreur_restauration:
                raise CommandError(
                    "Échec BDD et restauration NAS également en échec. "
                    f"Consultez immédiatement {journal}."
                ) from exc
            raise CommandError(
                f"Purge annulée et NAS restauré : {exc}. Journal : {journal}"
            ) from exc

        self.stdout.write(self.style.SUCCESS(f"Canari DN {numero} purgé."))
        self.stdout.write(f"Répertoire récupérable pendant 30 jours : {destination}")
        self.stdout.write(f"Journal : {journal}")

    @staticmethod
    def _unite(manifeste, numero):
        contenu = json.loads(Path(manifeste).read_text(encoding="utf-8"))
        unites = [
            unite for unite in contenu["unites"]
            if unite["type"] == "DN" and str(unite["numero"]) == numero
        ]
        if len(unites) != 1:
            raise CommandError("Unité DN absente ou ambiguë dans le manifeste.")
        return unites[0]

    @staticmethod
    def _chemins_nas(unite, numero):
        racine = os.environ.get("NAS_ROOT")
        if not racine:
            raise CommandError("NAS_ROOT n'est pas configuré.")
        if racine.startswith("\\\\"):
            racine = ntpath.normpath(racine)
        relatif = str(unite["emplacements"][0]).replace("\\", "/").strip("/")
        if not relatif or ".." in relatif.split("/"):
            raise CommandError("Emplacement NAS dangereux ou invalide.")
        joindre = ntpath.join if racine.startswith("\\\\") else os.path.join
        source = joindre(racine, *relatif.split("/"))
        lot = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        destination = joindre(
            racine, "_corbeille_agida", lot, f"DN_{numero}", *relatif.split("/")
        )
        return source, destination

    @staticmethod
    def _ids_documents(dossier_id):
        demandes = list(
            Demande.objects.using("default").filter(id_dossier_id=dossier_id)
            .values_list("id", flat=True)
        )
        messages = list(
            Message.objects.using("default").filter(id_dossier_id=dossier_id)
            .values_list("id", flat=True)
        )
        relectures = list(
            DossierRelecteur.objects.using("default").filter(id_dossier_id=dossier_id)
            .values_list("id", flat=True)
        )
        ids = set(
            DossierDocument.objects.using("default").filter(id_dossier_id=dossier_id)
            .values_list("id_document_id", flat=True)
        )
        ids.update(
            DossierChamp.objects.using("default")
            .filter(id_dossier_id=dossier_id, id_document_id__isnull=False)
            .values_list("id_document_id", flat=True)
        )
        ids.update(
            DemandeChamp.objects.using("default")
            .filter(id_demande_id__in=demandes, id_document_id__isnull=False)
            .values_list("id_document_id", flat=True)
        )
        ids.update(
            MessageDocument.objects.using("default").filter(id_message_id__in=messages)
            .values_list("id_document_id", flat=True)
        )
        ids.update(
            DossierRelecteurDocument.objects.using("default")
            .filter(id_dossier_relecteur_id__in=relectures)
            .values_list("id_document_id", flat=True)
        )
        ids.update(
            EmailOutbox.objects.using("default")
            .filter(id_dossier_id=dossier_id, id_document_id__isnull=False)
            .values_list("id_document_id", flat=True)
        )
        return ids

    @staticmethod
    def _est_windows_ou_unc(chemin):
        return platform.system() == "Windows" or chemin.startswith("\\\\")

    def _deplacer(self, source, destination):
        if self._est_windows_ou_unc(source):
            if not smbclient.path.exists(source):
                raise CommandError(f"Source NAS introuvable : {source}")
            if smbclient.path.exists(destination):
                raise CommandError(f"Destination NAS déjà existante : {destination}")
            smbclient.makedirs(ntpath.dirname(destination), exist_ok=True)
            smbclient.rename(source, destination)
            return
        if not os.path.exists(source):
            raise CommandError(f"Source NAS introuvable : {source}")
        if os.path.exists(destination):
            raise CommandError(f"Destination NAS déjà existante : {destination}")
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        os.rename(source, destination)

    @staticmethod
    def _creer_journal(manifeste, numero, source, destination):
        dossier = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve() / "executions"
        dossier.mkdir(parents=True, exist_ok=True)
        horodatage = timezone.localtime().strftime("%Y%m%d_%H%M%S")
        chemin = dossier / f"purge_canari_DN_{numero}_{horodatage}.json"
        donnees = {
            "cree_le": timezone.now().isoformat(),
            "statut": "prepare",
            "numero_dn": numero,
            "manifeste": manifeste,
            "source_nas": source,
            "destination_nas": destination,
        }
        chemin.write_text(
            json.dumps(donnees, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return chemin

    @staticmethod
    def _maj_journal(chemin, statut, **informations):
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
        donnees.update(informations)
        donnees["statut"] = statut
        donnees["mis_a_jour_le"] = timezone.now().isoformat()
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(
            json.dumps(donnees, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporaire.replace(chemin)
