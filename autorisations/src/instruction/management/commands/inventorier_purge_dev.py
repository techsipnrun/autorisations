from collections import defaultdict
import csv
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import platform
import re

from dateutil.relativedelta import relativedelta
import smbclient
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections
from django.db.models import Max, Q
from django.utils import timezone

from autorisations.models.models_avis import Avis, AvisDocument, DossierAvis
from autorisations.models.models_documents import (
    DossierDocument,
    DossierManifSportiveDocument,
    DossierRelecteurDocument,
    MessageDocument,
)
from autorisations.models.models_instruction import (
    Demande,
    DemandeChamp,
    Dossier,
    DossierAction,
    DossierChamp,
    DossierManifestationLiaison,
    DossierManifSportive,
    DossierNote,
    Message,
)
from autorisations.models.models_utilisateurs import DossierRelecteur, EmailOutbox


ETAPES_TERMINEES = {
    "Accepté",
    "Refusé",
    "Non soumis à autorisation",
    "Annulé",
}

# Ces répertoires sont gérés par le NAS ou par le futur mécanisme de purge
# AGIDA. Ils ne constituent jamais des dossiers métier orphelins.
REPERTOIRES_NAS_IGNORES = {
    "_corbeille_agida",
    "@recycle",
    "@eadir",
    "#recycle",
    "$recycle.bin",
    ".snapshot",
}


class Command(BaseCommand):
    help = (
        "Inventorie les dossiers de développement potentiellement purgeables. "
        "Cette commande ne supprime et ne modifie aucune donnée."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--months",
            type=int,
            default=12,
            help="Ancienneté minimale en mois (12 par défaut).",
        )
        parser.add_argument(
            "--details",
            action="store_true",
            help="Affiche chaque candidat et son emplacement NAS.",
        )
        parser.add_argument(
            "--scan-nas",
            action="store_true",
            help="Calcule la taille des répertoires candidats sans les modifier.",
        )
        parser.add_argument(
            "--rapport-csv",
            action="store_true",
            help="Génère un rapport CSV dans PURGE_BDD_ARCHIVE_ROOT/rapports.",
        )
        parser.add_argument(
            "--scan-orphelins",
            action="store_true",
            help=(
                "Recherche sur le NAS les répertoires DN/DM absents de la BDD "
                "et plus anciens que le seuil."
            ),
        )
        parser.add_argument(
            "--manifeste",
            action="store_true",
            help=(
                "Fige les candidats dans un manifeste JSON associé à la dernière "
                "sauvegarde BDD vérifiée. Nécessite --scan-nas."
            ),
        )

    def handle(self, *args, **options):
        self._verifier_cible_developpement()

        months = options["months"]
        if months < 1:
            raise CommandError("--months doit être supérieur ou égal à 1.")
        if options["manifeste"] and not options["scan_nas"]:
            raise CommandError("--manifeste nécessite --scan-nas.")

        date_limite = timezone.now() - relativedelta(months=months)
        dossiers_dn = list(
            Dossier.objects.using("default")
            .filter(id_etape_dossier__etape__in=ETAPES_TERMINEES)
            .select_related("id_etape_dossier")
        )
        dossiers_dm = list(
            DossierManifSportive.objects.using("default")
            .filter(archive=True)
            .select_related("id_etape")
        )

        activites_dn = self._activites_dn(dossiers_dn)
        activites_dm = self._activites_dm(dossiers_dm)

        candidats_dn = {
            dossier.id: dossier
            for dossier in dossiers_dn
            if activites_dn[dossier.id] and activites_dn[dossier.id] < date_limite
        }
        candidats_dm = {
            dossier.id: dossier
            for dossier in dossiers_dm
            if activites_dm[dossier.id] and activites_dm[dossier.id] < date_limite
        }

        liaisons = list(
            DossierManifestationLiaison.objects.using("default")
            .all()
        )
        ids_dn_lies = {liaison.id_dossier_id for liaison in liaisons}
        ids_dm_lies = {liaison.id_dossier_manif_id for liaison in liaisons}

        ensembles_complets = [
            liaison
            for liaison in liaisons
            if liaison.id_dossier_id in candidats_dn
            and liaison.id_dossier_manif_id in candidats_dm
        ]
        ids_dn_complets = {liaison.id_dossier_id for liaison in ensembles_complets}
        ids_dm_complets = {liaison.id_dossier_manif_id for liaison in ensembles_complets}

        dn_seuls = [
            dossier
            for identifiant, dossier in candidats_dn.items()
            if identifiant not in ids_dn_lies
        ]
        dm_seuls = [
            dossier
            for identifiant, dossier in candidats_dm.items()
            if identifiant not in ids_dm_lies
        ]

        # Un membre ancien d'un couple n'est jamais proposé seul si l'autre
        # membre est trop récent ou n'est pas dans un état terminal.
        couples_bloques = sum(
            1
            for liaison in liaisons
            if (
                liaison.id_dossier_id in candidats_dn
                or liaison.id_dossier_manif_id in candidats_dm
            )
            and (
                liaison.id_dossier_id not in ids_dn_complets
                or liaison.id_dossier_manif_id not in ids_dm_complets
            )
        )

        unites = self._construire_unites(
            dn_seuls,
            dm_seuls,
            ensembles_complets,
            candidats_dn,
            candidats_dm,
            activites_dn,
            activites_dm,
            options["scan_nas"],
        )
        orphelins_nas = []
        self._erreurs_scan_orphelins = []
        if options["scan_orphelins"]:
            orphelins_nas = self._inventorier_orphelins_nas(date_limite)

        self.stdout.write(self.style.MIGRATE_HEADING("Inventaire de purge DEV"))
        self.stdout.write(f"Date limite d'activité : {date_limite:%d/%m/%Y %H:%M}")
        self.stdout.write(
            f"Dossiers DN terminés analysés : {len(dossiers_dn)} "
            f"({len(dossiers_dn) - len(candidats_dn)} écartés pour activité récente)"
        )
        if options["scan_nas"]:
            taille_totale = sum(unite["taille_nas_octets"] or 0 for unite in unites)
            erreurs_nas = sum(1 for unite in unites if unite["erreur_nas"])
            self.stdout.write(f"Volume NAS potentiel : {self._taille_lisible(taille_totale)}")
            self.stdout.write(f"Erreurs de lecture NAS : {erreurs_nas}")
        if options["scan_orphelins"]:
            taille_orpheline = sum(
                orphelin["taille_nas_octets"] or 0 for orphelin in orphelins_nas
            )
            erreurs_orphelins = len(self._erreurs_scan_orphelins)
            self.stdout.write(f"Répertoires NAS orphelins anciens : {len(orphelins_nas)}")
            self.stdout.write(f"Volume NAS orphelin ancien : {self._taille_lisible(taille_orpheline)}")
            self.stdout.write(f"Erreurs sur les orphelins : {erreurs_orphelins}")
        self.stdout.write(
            f"Dossiers DM archivés analysés : {len(dossiers_dm)} "
            f"({len(dossiers_dm) - len(candidats_dm)} écartés pour activité récente)"
        )
        self.stdout.write(f"Dossiers DN seuls candidats : {len(dn_seuls)}")
        self.stdout.write(f"Dossiers DM seuls candidats : {len(dm_seuls)}")
        self.stdout.write(f"Ensembles complets DM–DN candidats : {len(ensembles_complets)}")
        self.stdout.write(f"Couples protégés car partiellement éligibles : {couples_bloques}")
        self.stdout.write(
            f"Total d'unités de purge potentielles : "
            f"{len(dn_seuls) + len(dm_seuls) + len(ensembles_complets)}"
        )

        if options["details"]:
            self.stdout.write("")
            for unite in unites:
                taille = (
                    self._taille_lisible(unite["taille_nas_octets"])
                    if options["scan_nas"] and unite["taille_nas_octets"] is not None
                    else "non calculée"
                )
                self.stdout.write(
                    f"[{unite['type']} {unite['numero']}] dernière activité "
                    f"{unite['derniere_activite']:%d/%m/%Y} | "
                    f"documents={unite['documents']} dont partagés={unite['documents_partages']} | "
                    f"messages={unite['messages']} | avis={unite['avis']} "
                    f"dont partagés={unite['avis_partages']} | "
                    f"taille NAS={taille} | {' ; '.join(unite['emplacements'])}"
                )

        if options["rapport_csv"]:
            chemin_rapport = self._ecrire_rapport_csv(unites, months)
            self.stdout.write(self.style.SUCCESS(f"Rapport CSV : {chemin_rapport}"))
            if options["scan_orphelins"]:
                chemin_orphelins = self._ecrire_rapport_orphelins_csv(orphelins_nas, months)
                self.stdout.write(
                    self.style.SUCCESS(f"Rapport CSV des orphelins : {chemin_orphelins}")
                )

        if options["manifeste"]:
            chemin_manifeste = self._ecrire_manifeste(unites, months, date_limite)
            self.stdout.write(
                self.style.SUCCESS(f"Manifeste de purge figé : {chemin_manifeste}")
            )

        if options["details"] and options["scan_orphelins"] and orphelins_nas:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("Répertoires NAS orphelins anciens"))
            for orphelin in orphelins_nas:
                self.stdout.write(
                    f"[ORPHELIN {orphelin['type']}] "
                    f"dernière modification {orphelin['derniere_modification']:%d/%m/%Y} | "
                    f"{self._taille_lisible(orphelin['taille_nas_octets'])} | "
                    f"{orphelin['emplacement']}"
                )
        if options["details"] and self._erreurs_scan_orphelins:
            self.stderr.write(self.style.ERROR("Erreurs rencontrées pendant le scan NAS"))
            for erreur in self._erreurs_scan_orphelins:
                self.stderr.write(
                    f"[{erreur['type']}] {erreur['emplacement']} : {erreur['erreur']}"
                )

        self.stdout.write("")
        self.stdout.write(
            self.style.WARNING(
                "Aucune donnée BDD et aucun fichier NAS n'ont été modifiés."
            )
        )

    def _construire_unites(
        self,
        dn_seuls,
        dm_seuls,
        ensembles_complets,
        candidats_dn,
        candidats_dm,
        activites_dn,
        activites_dm,
        scan_nas,
    ):
        definitions = []
        for dossier in dn_seuls:
            definitions.append((
                "DN",
                str(dossier.numero),
                [dossier.id],
                [],
                activites_dn[dossier.id],
                [dossier.emplacement],
            ))
        for dossier in dm_seuls:
            definitions.append((
                "DM",
                str(dossier.numero_dossier_declaration_manifestations),
                [],
                [dossier.id],
                activites_dm[dossier.id],
                [dossier.emplacement],
            ))
        for liaison in ensembles_complets:
            dossier_dn = candidats_dn[liaison.id_dossier_id]
            dossier_dm = candidats_dm[liaison.id_dossier_manif_id]
            definitions.append((
                "COMPLET",
                f"DN {dossier_dn.numero} / DM {dossier_dm.numero_dossier_declaration_manifestations}",
                [dossier_dn.id],
                [dossier_dm.id],
                max(activites_dn[dossier_dn.id], activites_dm[dossier_dm.id]),
                [dossier_dn.emplacement, dossier_dm.emplacement],
            ))

        unites = []
        for type_unite, numero, ids_dn, ids_dm, derniere_activite, emplacements in definitions:
            statistiques = self._statistiques_bdd(ids_dn, ids_dm)
            taille_nas = None
            erreur_nas = ""
            if scan_nas:
                try:
                    taille_nas = sum(self._taille_repertoire_nas(path) for path in emplacements)
                except Exception as exc:
                    erreur_nas = str(exc)

            if type_unite == "DN":
                cle = f"DN:{numero}"
            elif type_unite == "DM":
                cle = f"DM:{numero}"
            else:
                correspondance = re.fullmatch(r"DN (\d+) / DM (\d+)", numero)
                cle = (
                    f"DN:{correspondance.group(1)}+DM:{correspondance.group(2)}"
                    if correspondance else f"COMPLET:{numero}"
                )
            unites.append({
                "cle": cle,
                "type": type_unite,
                "numero": numero,
                "ids_dn": ids_dn,
                "ids_dm": ids_dm,
                "derniere_activite": derniere_activite,
                "emplacements": emplacements,
                "taille_nas_octets": taille_nas,
                "erreur_nas": erreur_nas,
                **statistiques,
            })

        return sorted(unites, key=lambda unite: (unite["type"], unite["numero"]))

    def _statistiques_bdd(self, ids_dn, ids_dm):
        messages = Message.objects.using("default").filter(id_dossier_id__in=ids_dn)
        ids_messages = list(messages.values_list("id", flat=True))
        ids_demandes = list(
            Demande.objects.using("default")
            .filter(id_dossier_id__in=ids_dn)
            .values_list("id", flat=True)
        )
        ids_relectures = list(
            DossierRelecteur.objects.using("default")
            .filter(id_dossier_id__in=ids_dn)
            .values_list("id", flat=True)
        )

        ids_avis = set(
            Avis.objects.using("default")
            .filter(id_dossier_id__in=ids_dn)
            .values_list("id", flat=True)
        )
        ids_avis.update(
            DossierAvis.objects.using("default")
            .filter(id_dossier_id__in=ids_dn)
            .values_list("id_avis_id", flat=True)
        )
        avis_partages = sum(
            1
            for avis_id in ids_avis
            if (
                DossierAvis.objects.using("default")
                .filter(id_avis_id=avis_id)
                .exclude(id_dossier_id__in=ids_dn)
                .exists()
                or Avis.objects.using("default")
                .filter(id=avis_id)
                .exclude(Q(id_dossier_id__in=ids_dn) | Q(id_dossier_id__isnull=True))
                .exists()
            )
        )
        ids_messages_avis = list(
            Message.objects.using("default")
            .filter(id_avis_id__in=ids_avis)
            .values_list("id", flat=True)
        )
        ids_messages_tous = set(ids_messages) | set(ids_messages_avis)

        ids_documents = set(
            DossierDocument.objects.using("default")
            .filter(id_dossier_id__in=ids_dn)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            DossierManifSportiveDocument.objects.using("default")
            .filter(id_dossier_manif_sportive_id__in=ids_dm)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            DossierChamp.objects.using("default")
            .filter(id_dossier_id__in=ids_dn, id_document_id__isnull=False)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            DemandeChamp.objects.using("default")
            .filter(id_demande_id__in=ids_demandes, id_document_id__isnull=False)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            MessageDocument.objects.using("default")
            .filter(id_message_id__in=ids_messages_tous)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            AvisDocument.objects.using("default")
            .filter(id_avis_id__in=ids_avis)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            DossierRelecteurDocument.objects.using("default")
            .filter(id_dossier_relecteur_id__in=ids_relectures)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            EmailOutbox.objects.using("default")
            .filter(id_dossier_id__in=ids_dn, id_document_id__isnull=False)
            .values_list("id_document_id", flat=True)
        )
        ids_documents.update(
            EmailOutbox.objects.using("default")
            .filter(id_dossier_dm_id__in=ids_dm, id_document_id__isnull=False)
            .values_list("id_document_id", flat=True)
        )
        for projet_acte_id, rapport_instance_id, projet_avis_id in (
            Avis.objects.using("default")
            .filter(id__in=ids_avis)
            .values_list("id_projet_acte_id", "id_rapport_instance_id", "id_projet_avis_id")
        ):
            ids_documents.update(
                identifiant
                for identifiant in (projet_acte_id, rapport_instance_id, projet_avis_id)
                if identifiant
            )

        documents_partages = 0
        for document_id in ids_documents:
            partage = (
                DossierDocument.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(id_dossier_id__in=ids_dn)
                .exists()
                or DossierManifSportiveDocument.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(id_dossier_manif_sportive_id__in=ids_dm)
                .exists()
                or MessageDocument.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(id_message_id__in=ids_messages_tous)
                .exists()
                or AvisDocument.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(id_avis_id__in=ids_avis)
                .exists()
                or Avis.objects.using("default")
                .exclude(id__in=ids_avis)
                .filter(id_projet_acte_id=document_id)
                .exists()
                or Avis.objects.using("default")
                .exclude(id__in=ids_avis)
                .filter(id_rapport_instance_id=document_id)
                .exists()
                or Avis.objects.using("default")
                .exclude(id__in=ids_avis)
                .filter(id_projet_avis_id=document_id)
                .exists()
                or DossierChamp.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(id_dossier_id__in=ids_dn)
                .exists()
                or DemandeChamp.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(id_demande_id__in=ids_demandes)
                .exists()
                or DossierRelecteurDocument.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(id_dossier_relecteur_id__in=ids_relectures)
                .exists()
                or EmailOutbox.objects.using("default")
                .filter(id_document_id=document_id)
                .exclude(
                    Q(id_dossier_id__in=ids_dn)
                    | Q(id_dossier_dm_id__in=ids_dm)
                )
                .exists()
            )
            if partage:
                documents_partages += 1

        return {
            "messages": len(ids_messages_tous),
            "avis": len(ids_avis),
            "avis_partages": avis_partages,
            "documents": len(ids_documents),
            "documents_partages": documents_partages,
            "actions": DossierAction.objects.using("default").filter(id_dossier_id__in=ids_dn).count(),
            "notes": DossierNote.objects.using("default").filter(
                id_dossier_id__in=ids_dn
            ).count() + DossierNote.objects.using("default").filter(
                id_dossier_manif_sportive_id__in=ids_dm
            ).count(),
            "mails": EmailOutbox.objects.using("default").filter(
                id_dossier_id__in=ids_dn
            ).count() + EmailOutbox.objects.using("default").filter(
                id_dossier_dm_id__in=ids_dm
            ).count(),
        }

    def _taille_repertoire_nas(self, emplacement):
        nas_root = os.environ.get("NAS_ROOT")
        if not nas_root:
            raise CommandError("NAS_ROOT n'est pas configuré.")

        chemin = os.path.join(nas_root, emplacement)
        taille = 0
        if platform.system() == "Windows" or chemin.startswith("\\\\"):
            if not smbclient.path.exists(chemin):
                return 0
            for racine, _, fichiers in smbclient.walk(chemin):
                for fichier in fichiers:
                    taille += smbclient.path.getsize(os.path.join(racine, fichier))
            return taille

        if not os.path.exists(chemin):
            return 0
        for racine, _, fichiers in os.walk(chemin):
            for fichier in fichiers:
                try:
                    taille += os.path.getsize(os.path.join(racine, fichier))
                except OSError:
                    # Le dossier peut changer pendant cet inventaire non bloquant.
                    continue
        return taille

    def _inventorier_orphelins_nas(self, date_limite):
        nas_root = os.environ.get("NAS_ROOT")
        if not nas_root:
            raise CommandError("NAS_ROOT n'est pas configuré.")

        emplacements_connus = {
            self._normaliser_chemin_relatif(emplacement)
            for emplacement in Dossier.objects.using("default")
            .exclude(emplacement__isnull=True)
            .values_list("emplacement", flat=True)
        }
        emplacements_connus.update(
            self._normaliser_chemin_relatif(emplacement)
            for emplacement in DossierManifSportive.objects.using("default")
            .exclude(emplacement__isnull=True)
            .values_list("emplacement", flat=True)
        )

        racines_possibles = self._trouver_racines_dossiers_nas(nas_root)
        orphelins = []
        for type_dossier, chemin_absolu, chemin_relatif in racines_possibles:
            if self._normaliser_chemin_relatif(chemin_relatif) in emplacements_connus:
                continue
            try:
                taille, derniere_modification = self._statistiques_repertoire_nas(chemin_absolu)
                erreur = ""
            except Exception as exc:
                self._erreurs_scan_orphelins.append({
                    "type": type_dossier,
                    "emplacement": chemin_relatif,
                    "erreur": str(exc),
                })
                continue

            # Une erreur ou une date indéterminable ne doit jamais rendre un
            # répertoire éligible à une future suppression.
            if not derniere_modification or derniere_modification >= date_limite:
                continue

            orphelins.append({
                "type": type_dossier,
                "emplacement": chemin_relatif,
                "derniere_modification": derniere_modification,
                "taille_nas_octets": taille,
                "erreur_nas": "",
            })

        return sorted(orphelins, key=lambda item: (item["type"], item["emplacement"]))

    def _trouver_racines_dossiers_nas(self, nas_root):
        racines = {}
        for racine, dossiers, _ in self._parcourir_nas(nas_root):
            relatif_racine = self._chemin_relatif_nas(nas_root, racine)
            if self._est_chemin_nas_ignore(relatif_racine):
                dossiers[:] = []
                continue

            for dossier in list(dossiers):
                relatif = self._normaliser_chemin_relatif(
                    f"{relatif_racine}/{dossier}" if relatif_racine else dossier
                )
                if self._est_chemin_nas_ignore(relatif):
                    # Empêche os.walk/smbclient.walk de descendre dans les
                    # corbeilles, snapshots et métadonnées du NAS.
                    dossiers.remove(dossier)
                    continue
                type_dossier = self._type_racine_dossier(relatif)
                if not type_dossier:
                    continue
                absolu = os.path.join(racine, dossier)
                racines[relatif.casefold()] = (type_dossier, absolu, relatif)
                # Une racine de dossier trouvée est une unité atomique : ne
                # pas interpréter un de ses sous-répertoires comme un dossier.
                dossiers.remove(dossier)

        return list(racines.values())

    @staticmethod
    def _est_chemin_nas_ignore(chemin_relatif):
        chemin = Command._normaliser_chemin_relatif(chemin_relatif)
        if not chemin:
            return False
        premier_repertoire = chemin.split("/", 1)[0].casefold()
        return premier_repertoire in REPERTOIRES_NAS_IGNORES

    def _parcourir_nas(self, chemin):
        if platform.system() == "Windows" or chemin.startswith("\\\\"):
            return smbclient.walk(chemin)
        return os.walk(chemin)

    def _statistiques_repertoire_nas(self, chemin):
        taille = 0
        dates_modification = [self._date_modification_nas(chemin)]
        for racine, dossiers, fichiers in self._parcourir_nas(chemin):
            for nom in dossiers:
                dates_modification.append(
                    self._date_modification_nas(os.path.join(racine, nom))
                )
            for nom in fichiers:
                fichier = os.path.join(racine, nom)
                taille += self._taille_fichier_nas(fichier)
                dates_modification.append(self._date_modification_nas(fichier))
        return taille, max(dates_modification)

    @staticmethod
    def _date_modification_nas(chemin):
        if platform.system() == "Windows" or chemin.startswith("\\\\"):
            timestamp = smbclient.stat(chemin).st_mtime
        else:
            timestamp = os.stat(chemin).st_mtime
        return datetime.fromtimestamp(timestamp, tz=timezone.get_current_timezone())

    @staticmethod
    def _taille_fichier_nas(chemin):
        if platform.system() == "Windows" or chemin.startswith("\\\\"):
            return smbclient.path.getsize(chemin)
        return os.path.getsize(chemin)

    @staticmethod
    def _normaliser_chemin_relatif(chemin):
        return re.sub(r"/+", "/", str(chemin or "").replace("\\", "/")).strip("/")

    def _chemin_relatif_nas(self, nas_root, chemin):
        racine = self._normaliser_chemin_relatif(nas_root)
        chemin_normalise = self._normaliser_chemin_relatif(chemin)
        if chemin_normalise.casefold() == racine.casefold():
            return ""
        prefixe = f"{racine}/"
        if not chemin_normalise.casefold().startswith(prefixe.casefold()):
            raise CommandError(f"Chemin NAS hors racine détecté : {chemin}")
        return chemin_normalise[len(prefixe):]

    @staticmethod
    def _type_racine_dossier(emplacement):
        morceaux = emplacement.split("/")
        nom = morceaux[-1] if morceaux else ""
        if re.match(r"^\d{7,9}_", nom):
            return "DN"
        if (
            len(morceaux) == 4
            and morceaux[0].casefold() == "manifestations_sportives"
            and re.fullmatch(r"\d{4}", morceaux[1])
            and morceaux[2].casefold() == "declaration manifestations"
        ):
            return "DM"
        return None

    def _ecrire_rapport_csv(self, unites, months):
        racine = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve()
        dossier_rapports = racine / "rapports"
        dossier_rapports.mkdir(parents=True, exist_ok=True)
        horodatage = timezone.now().strftime("%Y%m%d_%H%M%S")
        chemin = dossier_rapports / f"inventaire_purge_{months}mois_{horodatage}.csv"
        champs = [
            "cle",
            "type",
            "numero",
            "derniere_activite",
            "emplacements",
            "taille_nas",
            "taille_nas_octets",
            "erreur_nas",
            "messages",
            "avis",
            "avis_partages",
            "documents",
            "documents_partages",
            "actions",
            "notes",
            "mails",
        ]
        with chemin.open("w", encoding="utf-8-sig", newline="") as fichier:
            writer = csv.DictWriter(fichier, fieldnames=champs, delimiter=";")
            writer.writeheader()
            for unite in unites:
                ligne = dict(unite)
                ligne["derniere_activite"] = unite["derniere_activite"].isoformat()
                ligne["emplacements"] = " | ".join(unite["emplacements"])
                ligne["taille_nas"] = (
                    self._taille_lisible(unite["taille_nas_octets"])
                    if unite["taille_nas_octets"] is not None
                    else "non calculée"
                )
                writer.writerow({champ: ligne.get(champ, "") for champ in champs})
        return chemin

    def _ecrire_manifeste(self, unites, months, date_limite):
        if not unites:
            raise CommandError("Aucun candidat : aucun manifeste n'a été créé.")

        unites_sures = []
        unites_exclues = []
        for unite in unites:
            motifs = []
            if unite["erreur_nas"]:
                motifs.append(f"erreur NAS : {unite['erreur_nas']}")
            if unite["documents_partages"]:
                motifs.append(
                    f"{unite['documents_partages']} document(s) partagé(s)"
                )
            if unite["avis_partages"]:
                motifs.append(f"{unite['avis_partages']} avis partagé(s)")
            if motifs:
                unites_exclues.append({
                    "cle": unite["cle"],
                    "type": unite["type"],
                    "numero": unite["numero"],
                    "motifs": motifs,
                })
            else:
                unites_sures.append(unite)

        if not unites_sures:
            raise CommandError(
                "Toutes les unités sont ambiguës : aucun manifeste exécutable créé."
            )
        for unite in unites_exclues:
            self.stdout.write(self.style.WARNING(
                f"Unité exclue du manifeste [{unite['cle']}] : "
                f"{', '.join(unite['motifs'])}."
            ))

        archive, metadata_archive = self._derniere_sauvegarde_verifiee()
        maintenant = timezone.now()
        unites_json = []
        for unite in unites_sures:
            ligne = dict(unite)
            ligne["derniere_activite"] = unite["derniere_activite"].isoformat()
            unites_json.append(ligne)

        selection_canonique = json.dumps(
            unites_json,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        manifeste = {
            "version": 1,
            "cree_le": maintenant.isoformat(),
            "environnement": "dev",
            "seuil_mois": months,
            "date_limite_activite": date_limite.isoformat(),
            "nombre_unites": len(unites_json),
            "nombre_unites_exclues": len(unites_exclues),
            "taille_nas_octets": sum(
                unite["taille_nas_octets"] or 0 for unite in unites_sures
            ),
            "selection_sha256": hashlib.sha256(selection_canonique).hexdigest(),
            "sauvegarde_bdd": {
                "chemin": str(archive),
                "sha256": metadata_archive["sha256"],
            },
            # Les orphelins NAS feront l'objet d'un lot séparé : ils n'ont
            # aucune ligne BDD permettant une restauration symétrique.
            "inclut_orphelins_nas": False,
            "unites_exclues": unites_exclues,
            "unites": unites_json,
        }

        contenu = json.dumps(
            manifeste, ensure_ascii=False, sort_keys=True, indent=2
        ) + "\n"
        racine = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve()
        dossier = racine / "lots"
        dossier.mkdir(parents=True, exist_ok=True)
        horodatage = timezone.localtime(maintenant).strftime("%Y%m%d_%H%M%S")
        chemin = dossier / f"lot_purge_{months}mois_{horodatage}.json"
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(contenu, encoding="utf-8")
        temporaire.replace(chemin)
        empreinte = hashlib.sha256(contenu.encode("utf-8")).hexdigest()
        chemin.with_suffix(".json.sha256").write_text(
            f"{empreinte}  {chemin.name}\n", encoding="utf-8"
        )
        return chemin

    @staticmethod
    def _derniere_sauvegarde_verifiee():
        dossier = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve() / "sauvegardes"
        metadonnees = sorted(
            dossier.glob("agida_dev_avant_purge_*.dump.json"),
            key=lambda chemin: chemin.stat().st_mtime,
            reverse=True,
        )
        for metadata in metadonnees:
            try:
                contenu = json.loads(metadata.read_text(encoding="utf-8"))
                archive = metadata.with_suffix("")
                if (
                    contenu.get("environnement") == "dev"
                    and contenu.get("verification_pg_restore") is True
                    and archive.is_file()
                    and Command._sha256_fichier(archive) == contenu.get("sha256")
                ):
                    return archive, contenu
            except (OSError, ValueError, TypeError):
                continue
        raise CommandError(
            "Aucune sauvegarde BDD vérifiée compatible n'a été trouvée. "
            "Relancez d'abord sauvegarder_bdd_dev avec sa version actuelle."
        )

    @staticmethod
    def _sha256_fichier(chemin):
        empreinte = hashlib.sha256()
        with chemin.open("rb") as fichier:
            for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
                empreinte.update(bloc)
        return empreinte.hexdigest()

    def _ecrire_rapport_orphelins_csv(self, orphelins, months):
        racine = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve()
        dossier_rapports = racine / "rapports"
        dossier_rapports.mkdir(parents=True, exist_ok=True)
        horodatage = timezone.now().strftime("%Y%m%d_%H%M%S")
        chemin = dossier_rapports / f"orphelins_nas_{months}mois_{horodatage}.csv"
        champs = [
            "type",
            "emplacement",
            "derniere_modification",
            "taille_nas",
            "taille_nas_octets",
            "erreur_nas",
        ]
        with chemin.open("w", encoding="utf-8-sig", newline="") as fichier:
            writer = csv.DictWriter(fichier, fieldnames=champs, delimiter=";")
            writer.writeheader()
            for orphelin in orphelins:
                ligne = dict(orphelin)
                ligne["derniere_modification"] = orphelin["derniere_modification"].isoformat()
                ligne["taille_nas"] = self._taille_lisible(
                    orphelin["taille_nas_octets"]
                )
                writer.writerow(ligne)
        return chemin

    @staticmethod
    def _taille_lisible(nombre_octets):
        valeur = float(nombre_octets or 0)
        for unite in ("o", "Ko", "Mo", "Go", "To"):
            if valeur < 1024 or unite == "To":
                return f"{valeur:.1f} {unite}"
            valeur /= 1024

    def _verifier_cible_developpement(self):
        if settings.ENVIRONMENT != "dev":
            raise CommandError("Cette commande est réservée à l'environnement de développement.")

        try:
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "SELECT environnement FROM maintenance.environnement_agida WHERE id = true"
                )
                ligne = cursor.fetchone()
        except Exception as exc:
            raise CommandError(
                "Marqueur de la BDD de développement absent ou inaccessible."
            ) from exc

        if not ligne or ligne[0] != "dev":
            raise CommandError("La BDD cible n'est pas marquée comme environnement 'dev'.")

    def _activites_dn(self, dossiers):
        ids = [dossier.id for dossier in dossiers]
        activites = defaultdict(list)
        for dossier in dossiers:
            activites[dossier.id].extend(
                date
                for date in (
                    dossier.date_depot,
                    dossier.date_debut_instruction,
                    dossier.date_fin_instruction,
                )
                if date
            )

        self._ajouter_maximums(
            activites,
            DossierAction.objects.using("default").filter(id_dossier_id__in=ids),
            "id_dossier_id",
            "date",
        )
        self._ajouter_maximums(
            activites,
            Message.objects.using("default").filter(id_dossier_id__in=ids),
            "id_dossier_id",
            "date_envoi",
        )
        self._ajouter_maximums(
            activites,
            DossierNote.objects.using("default").filter(id_dossier_id__in=ids),
            "id_dossier_id",
            "date",
        )
        self._ajouter_maximums(
            activites,
            EmailOutbox.objects.using("default").filter(id_dossier_id__in=ids),
            "id_dossier_id",
            "derniere_tentative_envoi",
        )
        self._ajouter_maximums(
            activites,
            DossierDocument.objects.using("default").filter(id_dossier_id__in=ids),
            "id_dossier_id",
            "id_document__date",
        )

        self._ajouter_dates_avis(activites, ids)
        return {identifiant: max(dates) if dates else None for identifiant, dates in activites.items()}

    def _activites_dm(self, dossiers):
        ids = [dossier.id for dossier in dossiers]
        activites = defaultdict(list)
        for dossier in dossiers:
            activites[dossier.id].extend(
                date
                for date in (
                    dossier.date_depot,
                    dossier.date_debut_evenement,
                    dossier.date_fin_evenement,
                )
                if date
            )

        self._ajouter_maximums(
            activites,
            DossierNote.objects.using("default").filter(
                id_dossier_manif_sportive_id__in=ids
            ),
            "id_dossier_manif_sportive_id",
            "date",
        )
        self._ajouter_maximums(
            activites,
            EmailOutbox.objects.using("default").filter(id_dossier_dm_id__in=ids),
            "id_dossier_dm_id",
            "derniere_tentative_envoi",
        )
        self._ajouter_maximums(
            activites,
            DossierManifSportiveDocument.objects.using("default").filter(
                id_dossier_manif_sportive_id__in=ids
            ),
            "id_dossier_manif_sportive_id",
            "id_document__date",
        )
        return {identifiant: max(dates) if dates else None for identifiant, dates in activites.items()}

    def _ajouter_dates_avis(self, activites, ids_dossiers):
        avis_par_dossier = defaultdict(set)
        for dossier_id, avis_id in (
            Avis.objects.using("default")
            .filter(id_dossier_id__in=ids_dossiers)
            .values_list("id_dossier_id", "id")
        ):
            avis_par_dossier[dossier_id].add(avis_id)
        for dossier_id, avis_id in (
            DossierAvis.objects.using("default")
            .filter(id_dossier_id__in=ids_dossiers)
            .values_list("id_dossier_id", "id_avis_id")
        ):
            avis_par_dossier[dossier_id].add(avis_id)

        ids_avis = {avis_id for valeurs in avis_par_dossier.values() for avis_id in valeurs}
        dates_avis = {}
        for avis in Avis.objects.using("default").filter(id__in=ids_avis):
            dates = [
                date
                for date in (
                    avis.date_demande_avis,
                    avis.date_reponse_avis,
                    avis.date_presentation,
                    avis.date_transmission_cs,
                )
                if date
            ]
            dates_avis[avis.id] = max(dates) if dates else None

        for dossier_id, ids_avis_dossier in avis_par_dossier.items():
            activites[dossier_id].extend(
                dates_avis[avis_id]
                for avis_id in ids_avis_dossier
                if dates_avis.get(avis_id)
            )

    @staticmethod
    def _ajouter_maximums(activites, queryset, champ_groupe, champ_date):
        alias_date = "date_max"
        for ligne in queryset.values(champ_groupe).annotate(**{alias_date: Max(champ_date)}):
            if ligne[alias_date]:
                activites[ligne[champ_groupe]].append(ligne[alias_date])

    def _afficher_candidat(self, type_dossier, numero, derniere_activite, emplacement):
        self.stdout.write(
            f"[{type_dossier} {numero}] dernière activité "
            f"{derniere_activite:%d/%m/%Y} | {emplacement}"
        )
