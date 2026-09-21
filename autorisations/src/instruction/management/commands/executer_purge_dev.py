import json
import ntpath
import os
from pathlib import Path
import platform
import re

import smbclient
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from autorisations.models.models_avis import Avis, AvisDocument, DossierAvis
from autorisations.models.models_documents import (
    Document, DossierDocument, DossierManifSportiveDocument,
    DossierRelecteurDocument, MessageDocument,
)
from autorisations.models.models_instruction import (
    Demande, DemandeChamp, Dossier, DossierChamp, DossierManifSportive, Message,
)
from autorisations.models.models_utilisateurs import DossierRelecteur, EmailOutbox
from instruction.management.commands.inventorier_purge_dev import (
    Command as CommandeInventaire, ETAPES_TERMINEES,
)
from instruction.management.commands.verifier_purge_canari_dev import (
    Command as CommandeVerification,
)


class Command(BaseCommand):
    help = (
        "Purge des unités DN, DM ou complètes d'un manifeste DEV. "
        "Simulation par défaut et maximum 25 unités par appel."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifeste", required=True)
        parser.add_argument("--cles", nargs="+", help="Clés exactes, par exemple DN:123.")
        parser.add_argument("--limite", type=int, default=10)
        parser.add_argument("--execute", action="store_true")
        parser.add_argument(
            "--confirmation",
            help="Confirmation EXECUTER-<empreinte courte du manifeste>.",
        )

    def handle(self, *args, **options):
        inventaire = CommandeInventaire()
        inventaire._verifier_cible_developpement()
        chemin = Path(options["manifeste"]).expanduser().resolve()
        manifeste = CommandeVerification()._charger_et_verifier_manifeste(chemin)

        limite = options["limite"]
        if limite < 1 or limite > 25:
            raise CommandError("--limite doit être compris entre 1 et 25.")
        unites = manifeste.get("unites", [])
        if options.get("cles"):
            demandees = list(dict.fromkeys(options["cles"]))
            index = {unite.get("cle"): unite for unite in unites}
            absentes = [cle for cle in demandees if cle not in index]
            if absentes:
                raise CommandError(f"Clé(s) absente(s) du manifeste : {', '.join(absentes)}")
            selection = [index[cle] for cle in demandees]
        else:
            selection = unites[:limite]
        if len(selection) > limite:
            raise CommandError("La sélection dépasse --limite.")
        if not selection:
            raise CommandError("Aucune unité sélectionnée.")
        if options["execute"] and not options.get("cles"):
            raise CommandError("--cles est obligatoire avec --execute.")

        controles = [self._verifier_unite(unite, inventaire) for unite in selection]
        empreinte_courte = manifeste["selection_sha256"][:12]
        self.stdout.write(self.style.MIGRATE_HEADING(
            "Plan d'exécution" if options["execute"] else "Simulation de purge"
        ))
        for controle in controles:
            unite = controle["unite"]
            self.stdout.write(
                f"[{unite['cle']}] {len(unite['emplacements'])} répertoire(s), "
                f"{inventaire._taille_lisible(unite['taille_nas_octets'])}, "
                f"{unite['documents']} document(s), {unite['avis']} avis."
            )

        if not options["execute"]:
            self.stdout.write(self.style.WARNING(
                "SIMULATION uniquement. Pour exécuter cette sélection, ajoutez "
                f"--execute --confirmation EXECUTER-{empreinte_courte}."
            ))
            return
        if options.get("confirmation") != f"EXECUTER-{empreinte_courte}":
            raise CommandError(
                f"Confirmation incorrecte : EXECUTER-{empreinte_courte} est requis."
            )

        terminees = []
        for controle in controles:
            self._executer_unite(controle, chemin)
            terminees.append(controle["unite"]["cle"])
        self.stdout.write(self.style.SUCCESS(
            f"Purge terminée pour {len(terminees)} unité(s) : {', '.join(terminees)}"
        ))

    def _verifier_unite(self, unite, inventaire):
        ids_dn = unite.get("ids_dn") or []
        ids_dm = unite.get("ids_dm") or []
        dossiers_dn = list(Dossier.objects.using("default").filter(id__in=ids_dn)
                           .select_related("id_etape_dossier"))
        dossiers_dm = list(DossierManifSportive.objects.using("default").filter(id__in=ids_dm))
        if len(dossiers_dn) != len(ids_dn) or len(dossiers_dm) != len(ids_dm):
            raise CommandError(f"[{unite['cle']}] un dossier n'existe plus en BDD.")
        if any(d.id_etape_dossier.etape not in ETAPES_TERMINEES for d in dossiers_dn):
            raise CommandError(f"[{unite['cle']}] étape DN non terminale.")
        if any(not d.archive for d in dossiers_dm):
            raise CommandError(f"[{unite['cle']}] dossier DM non archivé.")

        emplacements = [inventaire._normaliser_chemin_relatif(d.emplacement)
                        for d in dossiers_dn + dossiers_dm]
        attendus = [inventaire._normaliser_chemin_relatif(p)
                    for p in unite.get("emplacements", [])]
        if emplacements != attendus:
            raise CommandError(f"[{unite['cle']}] les emplacements NAS ont changé.")
        activites = list(inventaire._activites_dn(dossiers_dn).values())
        activites += list(inventaire._activites_dm(dossiers_dm).values())
        derniere = max(date for date in activites if date)
        if derniere.isoformat() != unite.get("derniere_activite"):
            raise CommandError(f"[{unite['cle']}] l'activité a changé.")
        stats = inventaire._statistiques_bdd(ids_dn, ids_dm)
        for champ in ("messages", "avis", "avis_partages", "documents",
                      "documents_partages", "actions", "notes", "mails"):
            if stats[champ] != unite.get(champ):
                raise CommandError(f"[{unite['cle']}] le compteur {champ} a changé.")
        if stats["documents_partages"] or stats["avis_partages"]:
            raise CommandError(f"[{unite['cle']}] contient des éléments partagés.")
        taille = sum(inventaire._taille_repertoire_nas(d.emplacement)
                     for d in dossiers_dn + dossiers_dm)
        if taille != unite.get("taille_nas_octets"):
            raise CommandError(f"[{unite['cle']}] le contenu NAS a changé.")
        liens = self._liens(ids_dn, ids_dm)
        return {"unite": unite, "liens": liens}

    def _executer_unite(self, controle, manifeste):
        unite = controle["unite"]
        mouvements = self._mouvements(unite)
        journal = self._creer_journal(
            manifeste, unite, mouvements, controle["liens"]
        )
        effectues = []
        try:
            with transaction.atomic(using="default"):
                list(Dossier.objects.using("default").select_for_update()
                     .filter(id__in=unite["ids_dn"]))
                list(DossierManifSportive.objects.using("default").select_for_update()
                     .filter(id__in=unite["ids_dm"]))
                # Les contrôles sont rejoués sous verrou juste avant toute
                # mutation. Les liens enregistrés sont donc ceux réellement
                # supprimés, pas seulement ceux observés pendant la simulation.
                controle_final = self._verifier_unite(unite, CommandeInventaire())
                liens = controle_final["liens"]
                self._maj_journal(
                    journal,
                    "verifie",
                    ids_avis=liens["avis"],
                    ids_documents=liens["documents"],
                )
                for source, destination in mouvements:
                    self._deplacer(source, destination)
                    effectues.append((source, destination))
                self._maj_journal(journal, "nas_en_corbeille")

                Avis.objects.using("default").filter(id__in=liens["avis"]).delete()
                Dossier.objects.using("default").filter(id__in=unite["ids_dn"]).delete()
                DossierManifSportive.objects.using("default").filter(
                    id__in=unite["ids_dm"]
                ).delete()
                Document.objects.using("default").filter(
                    id__in=liens["documents"]
                ).delete()
            self._maj_journal(journal, "termine")
        except Exception as exc:
            erreurs = []
            for source, destination in reversed(effectues):
                try:
                    self._deplacer(destination, source)
                except Exception as restauration_exc:
                    erreurs.append(str(restauration_exc))
            self._maj_journal(journal, "echec", erreur=str(exc),
                              erreurs_restauration_nas=erreurs)
            if erreurs:
                raise CommandError(f"[{unite['cle']}] échec critique, voir {journal}.") from exc
            raise CommandError(f"[{unite['cle']}] échec, NAS restauré : {exc}") from exc

    @staticmethod
    def _liens(ids_dn, ids_dm):
        demandes = list(Demande.objects.using("default").filter(id_dossier_id__in=ids_dn)
                         .values_list("id", flat=True))
        relectures = list(DossierRelecteur.objects.using("default")
                          .filter(id_dossier_id__in=ids_dn).values_list("id", flat=True))
        avis = set(Avis.objects.using("default").filter(id_dossier_id__in=ids_dn)
                   .values_list("id", flat=True))
        avis.update(DossierAvis.objects.using("default").filter(id_dossier_id__in=ids_dn)
                    .values_list("id_avis_id", flat=True))
        messages = set(Message.objects.using("default").filter(id_dossier_id__in=ids_dn)
                       .values_list("id", flat=True))
        messages.update(Message.objects.using("default").filter(id_avis_id__in=avis)
                        .values_list("id", flat=True))
        documents = set(DossierDocument.objects.using("default")
                        .filter(id_dossier_id__in=ids_dn).values_list("id_document_id", flat=True))
        documents.update(DossierManifSportiveDocument.objects.using("default")
                         .filter(id_dossier_manif_sportive_id__in=ids_dm)
                         .values_list("id_document_id", flat=True))
        documents.update(DossierChamp.objects.using("default")
                         .filter(id_dossier_id__in=ids_dn, id_document_id__isnull=False)
                         .values_list("id_document_id", flat=True))
        documents.update(DemandeChamp.objects.using("default")
                         .filter(id_demande_id__in=demandes, id_document_id__isnull=False)
                         .values_list("id_document_id", flat=True))
        documents.update(MessageDocument.objects.using("default")
                         .filter(id_message_id__in=messages).values_list("id_document_id", flat=True))
        documents.update(AvisDocument.objects.using("default").filter(id_avis_id__in=avis)
                         .values_list("id_document_id", flat=True))
        documents.update(DossierRelecteurDocument.objects.using("default")
                         .filter(id_dossier_relecteur_id__in=relectures)
                         .values_list("id_document_id", flat=True))
        documents.update(EmailOutbox.objects.using("default")
                         .filter(Q(id_dossier_id__in=ids_dn) | Q(id_dossier_dm_id__in=ids_dm),
                                 id_document_id__isnull=False)
                         .values_list("id_document_id", flat=True))
        for valeurs in Avis.objects.using("default").filter(id__in=avis).values_list(
            "id_projet_acte_id", "id_rapport_instance_id", "id_projet_avis_id"
        ):
            documents.update(valeur for valeur in valeurs if valeur)
        return {"avis": sorted(avis), "documents": sorted(documents)}

    @staticmethod
    def _mouvements(unite):
        racine = os.environ.get("NAS_ROOT")
        if not racine:
            raise CommandError("NAS_ROOT n'est pas configuré.")
        unc = racine.startswith("\\\\")
        if unc:
            racine = ntpath.normpath(racine)
        joindre = ntpath.join if unc else os.path.join
        lot = timezone.localtime().strftime("%Y%m%d_%H%M%S_%f")
        cle = re.sub(r"[^A-Za-z0-9_-]+", "_", unite["cle"])
        mouvements = []
        for relatif_brut in unite["emplacements"]:
            relatif = str(relatif_brut).replace("\\", "/").strip("/")
            if not relatif or ".." in relatif.split("/"):
                raise CommandError("Emplacement NAS dangereux ou invalide.")
            source = joindre(racine, *relatif.split("/"))
            destination = joindre(racine, "_corbeille_agida", lot, cle,
                                   *relatif.split("/"))
            mouvements.append((source, destination))
        return mouvements

    @staticmethod
    def _deplacer(source, destination):
        unc = source.startswith("\\\\")
        if platform.system() == "Windows" or unc:
            if not smbclient.path.exists(source):
                raise CommandError(f"Source NAS introuvable : {source}")
            if smbclient.path.exists(destination):
                raise CommandError(f"Destination NAS déjà existante : {destination}")
            smbclient.makedirs(ntpath.dirname(destination), exist_ok=True)
            smbclient.rename(source, destination)
        else:
            if not os.path.exists(source):
                raise CommandError(f"Source NAS introuvable : {source}")
            if os.path.exists(destination):
                raise CommandError(f"Destination NAS déjà existante : {destination}")
            os.makedirs(os.path.dirname(destination), exist_ok=True)
            os.rename(source, destination)

    @staticmethod
    def _creer_journal(manifeste, unite, mouvements, liens):
        dossier = Path(settings.PURGE_BDD_ARCHIVE_ROOT).resolve() / "executions"
        dossier.mkdir(parents=True, exist_ok=True)
        nom = re.sub(r"[^A-Za-z0-9_-]+", "_", unite["cle"])
        horodatage = timezone.localtime().strftime("%Y%m%d_%H%M%S_%f")
        chemin = dossier / f"purge_{nom}_{horodatage}.json"
        contenu = {"cree_le": timezone.now().isoformat(), "statut": "prepare",
                   "cle": unite["cle"], "manifeste": str(manifeste),
                   "mouvements_nas": mouvements, "ids_dn": unite["ids_dn"],
                   "ids_dm": unite["ids_dm"], "ids_avis": liens["avis"],
                   "ids_documents": liens["documents"]}
        chemin.write_text(json.dumps(contenu, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        return chemin

    @staticmethod
    def _maj_journal(chemin, statut, **details):
        contenu = json.loads(chemin.read_text(encoding="utf-8"))
        contenu.update(details)
        contenu.update({"statut": statut, "mis_a_jour_le": timezone.now().isoformat()})
        temporaire = chemin.with_suffix(".json.tmp")
        temporaire.write_text(json.dumps(contenu, ensure_ascii=False, indent=2) + "\n",
                              encoding="utf-8")
        temporaire.replace(chemin)
