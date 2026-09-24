import logging
import os
import re
from urllib.parse import unquote, urljoin, urlsplit

import smbclient
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from autorisations.models.models_documents import (
    Document,
    DocumentFormat,
    DocumentNature,
    DossierManifSportiveDocument,
)
from autorisations.models.models_instruction import (
    AvisManifSportive,
    DossierManifSportive,
)
from autorisations.utils.nas_fonctions import ecrire_file_sur_nas
from declaration_manifestations.get_methods import (
    API_URL,
    SESSION,
    get_access_token,
    get_pj_avis,
)
from instruction.utils.files_utils import sanitiser_nom_fichier
from synchronisation.utils.conversion import parse_datetime_with_tz
from synchronisation.utils.fichiers import get_nom_disponible


logger = logging.getLogger("SYNCHRONISATION")


class Command(BaseCommand):
    help = (
        "Bancarise dans AGIDA les pièces jointes PDF déposées sur des avis "
        "Déclaration Manifestations. La commande est en simulation par défaut."
    )

    CONFIRMATION = "BANCARISER-ACTES-DM"
    SOUS_DOSSIER = "Annexes/Instruction"
    DESCRIPTION = "Acte envoyé sur Déclaration Manifestations."
    DESCRIPTION_ANNEXE = "Annexe envoyée sur Déclaration Manifestations."

    def add_arguments(self, parser):
        cible = parser.add_mutually_exclusive_group(required=True)
        cible.add_argument(
            "--dossiers",
            nargs="+",
            type=int,
            metavar="NUMERO_DM",
            help="Numéro(s) de dossier Déclaration Manifestations.",
        )
        cible.add_argument(
            "--avis",
            nargs="+",
            type=int,
            metavar="ID_AVIS_DM",
            help="Identifiant(s) d'avis Déclaration Manifestations.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Télécharge les fichiers, les écrit sur le NAS et crée les lignes BDD.",
        )
        parser.add_argument(
            "--confirmation",
            help=f"Confirmation obligatoire en exécution : {self.CONFIRMATION}.",
        )
        parser.add_argument(
            "--selection-fichiers",
            nargs="*",
            default=[],
            metavar="NOM_FICHIER",
            help=(
                "Noms exacts des arrêtés à retenir lorsqu'un avis contient "
                "plusieurs fichiers DIR-I-."
            ),
        )

    def handle(self, *args, **options):
        execute = options["execute"]
        if execute and options.get("confirmation") != self.CONFIRMATION:
            raise CommandError(
                "Confirmation incorrecte. Ajoutez "
                f"--confirmation {self.CONFIRMATION} pour exécuter la bancarisation."
            )

        nas_root = (os.environ.get("NAS_ROOT") or "").rstrip("\\/")
        if execute and not nas_root:
            raise CommandError("NAS_ROOT n'est pas configuré.")

        nature_arrete = DocumentNature.objects.filter(
            nature__iexact="Arrêté directeur"
        ).first()
        nature_annexe = DocumentNature.objects.filter(
            nature__iexact="Annexe instructeur DM"
        ).first()
        format_pdf = DocumentFormat.objects.filter(format__iexact="pdf").first()
        if not nature_arrete:
            raise CommandError("La nature documentaire 'Arrêté directeur' est introuvable.")
        if not nature_annexe:
            raise CommandError("La nature documentaire 'Annexe instructeur DM' est introuvable.")
        if not format_pdf:
            raise CommandError("Le format documentaire 'pdf' est introuvable.")

        cibles = self._charger_cibles(options)
        cibles.sort(key=self._date_tri_avis, reverse=True)
        self.fichiers_selectionnes = set(options.get("selection_fichiers") or [])
        token = get_access_token()
        if not token:
            raise CommandError("Impossible d'obtenir un jeton d'accès à l'API DM.")

        bilan = {
            "avis": 0,
            "pieces": 0,
            "a_bancariser": 0,
            "bancarisees": 0,
            "deja_presentes": 0,
            "ignorees": 0,
            "erreurs": 0,
        }
        # Détecte également les doublons de numéro entre plusieurs pièces du lot,
        # même si aucun de ces documents n'existe encore en BDD.
        self.numeros_planifies = {}

        titre_mode = "Exécution" if execute else "Simulation"
        self.stdout.write(f"{titre_mode} de la bancarisation des actes DM")
        logger.info("[BANCARISATION ACTES DM] %s démarrée.", titre_mode)

        for avis in cibles:
            bilan["avis"] += 1
            dossier = avis.id_dossier_manif_sportive
            numero_dm = dossier.numero_dossier_declaration_manifestations
            self._trace(
                f"[DOSSIER DM {numero_dm}] Avis DM {avis.id_avis_manif_sportive} analysé."
            )

            try:
                pieces = self._extraire_liste_pj(
                    get_pj_avis(token, avis.id_avis_manif_sportive)
                )
            except Exception as exc:
                bilan["erreurs"] += 1
                self._erreur(
                    f"[DOSSIER DM {numero_dm}] Impossible de récupérer les PJ de "
                    f"l'avis {avis.id_avis_manif_sportive} : {exc}"
                )
                continue

            pieces_avec_fichier = [pj for pj in pieces if self._url_piece(pj)]
            if not pieces_avec_fichier:
                self._trace(
                    f"[DOSSIER DM {numero_dm}] Aucune pièce jointe à bancariser sur l'avis."
                )
                continue

            bilan["pieces"] += len(pieces_avec_fichier)
            pieces_dir = [
                pj
                for pj in pieces_avec_fichier
                if self._titre_piece(pj).upper().startswith("DIR-I-")
            ]
            pieces_annexes = [
                pj for pj in pieces_avec_fichier if pj not in pieces_dir
            ]
            if len(pieces_dir) <= 1:
                arretes_retenus = pieces_dir
            else:
                arretes_retenus = [
                    pj
                    for pj in pieces_dir
                    if self._titre_piece(pj) in self.fichiers_selectionnes
                ]

            # Les fichiers non DIR-I- sont toujours bancarisés comme annexes.
            # Seules les versions DIR-I- non sélectionnées sont réellement ignorées.
            pieces_a_traiter = arretes_retenus + pieces_annexes
            pieces_ignorees = [pj for pj in pieces_dir if pj not in arretes_retenus]

            if len(pieces_avec_fichier) > 1:
                bilan["ignorees"] += len(pieces_ignorees)
                if pieces_a_traiter:
                    self._avertissement(
                        f"[DOSSIER DM {numero_dm}] Avis DM "
                        f"{avis.id_avis_manif_sportive} : "
                        f"{len(arretes_retenus)} arrêté(s) DIR-I- et "
                        f"{len(pieces_annexes)} annexe(s) à bancariser ; "
                        f"{len(pieces_ignorees)} ancienne(s) version(s) DIR-I- "
                        f"ignorée(s) et journalisée(s)"
                        + (
                            f" ({', '.join(self._libelle_piece(pj) for pj in pieces_ignorees)})."
                            if pieces_ignorees else "."
                        )
                    )
                else:
                    self._avertissement(
                        f"[DOSSIER DM {numero_dm}] Avis DM "
                        f"{avis.id_avis_manif_sportive} ignoré intégralement : "
                        f"{len(pieces_avec_fichier)} pièces jointes ont été trouvées "
                        f"({', '.join(self._libelle_piece(pj) for pj in pieces_avec_fichier)}). "
                        "Aucun arrêté n'a été sélectionné sans ambiguïté."
                    )
                    continue

            for pj in pieces_a_traiter:
                resultat = self._traiter_piece(
                    token=token,
                    avis=avis,
                    pj=pj,
                    nature_arrete=nature_arrete,
                    nature_annexe=nature_annexe,
                    format_pdf=format_pdf,
                    nas_root=nas_root,
                    execute=execute,
                )
                bilan[resultat] += 1

        self.stdout.write("")
        self.stdout.write("Bilan")
        self.stdout.write(f"Avis analysés : {bilan['avis']}")
        self.stdout.write(f"Pièces jointes trouvées : {bilan['pieces']}")
        if execute:
            self.stdout.write(f"Documents bancarisés : {bilan['bancarisees']}")
        else:
            self.stdout.write(f"Documents à bancariser : {bilan['a_bancariser']}")
        self.stdout.write(f"Documents déjà présents : {bilan['deja_presentes']}")
        self.stdout.write(f"Pièces ignorées : {bilan['ignorees']}")
        self.stdout.write(f"Erreurs : {bilan['erreurs']}")

        if execute:
            self.stdout.write(self.style.SUCCESS("Bancarisation terminée."))
        else:
            self.stdout.write(
                "SIMULATION uniquement : aucun fichier NAS et aucune donnée BDD "
                "n'ont été modifiés."
            )
            self.stdout.write(
                "Après contrôle, relancez avec --execute "
                f"--confirmation {self.CONFIRMATION}."
            )

        logger.info(
            "[BANCARISATION ACTES DM] Bilan : avis=%s, pièces=%s, à_bancariser=%s, "
            "bancarisées=%s, déjà_présentes=%s, ignorées=%s, erreurs=%s.",
            bilan["avis"],
            bilan["pieces"],
            bilan["a_bancariser"],
            bilan["bancarisees"],
            bilan["deja_presentes"],
            bilan["ignorees"],
            bilan["erreurs"],
        )

    def _charger_cibles(self, options):
        if options.get("dossiers"):
            valeurs = list(dict.fromkeys(options["dossiers"]))
            dossiers = {
                dossier.numero_dossier_declaration_manifestations: dossier
                for dossier in DossierManifSportive.objects.filter(
                    numero_dossier_declaration_manifestations__in=valeurs
                )
            }
            manquants = [numero for numero in valeurs if numero not in dossiers]
            if manquants:
                raise CommandError(
                    "Dossier(s) DM introuvable(s) en BDD : "
                    + ", ".join(map(str, manquants))
                )

            avis_par_dossier = {
                avis.id_dossier_manif_sportive_id: avis
                for avis in AvisManifSportive.objects.select_related(
                    "id_dossier_manif_sportive"
                ).filter(id_dossier_manif_sportive__in=dossiers.values())
            }
            sans_avis = [
                numero
                for numero in valeurs
                if dossiers[numero].id not in avis_par_dossier
            ]
            if sans_avis:
                raise CommandError(
                    "Aucun avis DM enregistré pour le(s) dossier(s) : "
                    + ", ".join(map(str, sans_avis))
                )
            return [avis_par_dossier[dossiers[numero].id] for numero in valeurs]

        valeurs = list(dict.fromkeys(options["avis"]))
        avis_trouves = {
            avis.id_avis_manif_sportive: avis
            for avis in AvisManifSportive.objects.select_related(
                "id_dossier_manif_sportive"
            ).filter(id_avis_manif_sportive__in=valeurs)
        }
        manquants = [identifiant for identifiant in valeurs if identifiant not in avis_trouves]
        if manquants:
            raise CommandError(
                "Avis DM introuvable(s) en BDD : " + ", ".join(map(str, manquants))
            )
        sans_dossier = [
            identifiant
            for identifiant in valeurs
            if avis_trouves[identifiant].id_dossier_manif_sportive_id is None
        ]
        if sans_dossier:
            raise CommandError(
                "Avis DM sans dossier AGIDA associé : "
                + ", ".join(map(str, sans_dossier))
            )
        return [avis_trouves[identifiant] for identifiant in valeurs]

    @staticmethod
    def _extraire_liste_pj(reponse):
        if isinstance(reponse, list):
            return reponse
        if isinstance(reponse, dict):
            for cle in ("results", "data", "pieces_jointes"):
                valeur = reponse.get(cle)
                if isinstance(valeur, list):
                    return valeur
        raise ValueError("format de réponse inattendu pour la liste des PJ d'avis")

    @staticmethod
    def _libelle_piece(pj):
        titre = Command._titre_piece(pj) or "nom inconnu"
        return f"id={pj.get('id')}, fichier='{titre}'"

    @staticmethod
    def _titre_piece(pj):
        url = Command._url_piece(pj) or ""
        return unquote(os.path.basename(urlsplit(url).path))

    @staticmethod
    def _url_piece(pj):
        # L'API DM n'emploie pas le même champ pour les PJ du dossier
        # (document_attache) et celles de l'avis (fichier).
        return pj.get("fichier") or pj.get("document_attache")

    def _traiter_piece(
        self, *, token, avis, pj, nature_arrete, nature_annexe, format_pdf,
        nas_root, execute
    ):
        dossier = avis.id_dossier_manif_sportive
        numero_dm = dossier.numero_dossier_declaration_manifestations
        url = self._url_piece(pj)
        pj_dm_id = pj.get("id")
        titre_source = unquote(os.path.basename(urlsplit(url).path))
        titre_source = sanitiser_nom_fichier(titre_source)

        if not titre_source:
            self._erreur(
                f"[DOSSIER DM {numero_dm}] PJ DM {pj_dm_id} ignorée : nom de fichier vide."
            )
            return "erreurs"
        extension = os.path.splitext(titre_source)[1].lower().lstrip(".")
        est_arrete = titre_source.upper().startswith("DIR-I-")
        if est_arrete:
            if extension != "pdf":
                self._avertissement(
                    f"[DOSSIER DM {numero_dm}] '{titre_source}' ignoré : seuls les "
                    "PDF peuvent être bancarisés comme arrêté directeur."
                )
                return "ignorees"
            numero_document = self._extraire_numero_acte(titre_source)
            if not numero_document:
                self._avertissement(
                    f"[DOSSIER DM {numero_dm}] Fichier '{titre_source}' ignoré : aucun "
                    "numéro n'a pu être extrait de son nom."
                )
                return "ignorees"
            nature_document = nature_arrete
            format_document = format_pdf
            description = self.DESCRIPTION
        else:
            numero_document = None
            nature_document = nature_annexe
            format_document = DocumentFormat.objects.filter(
                format__iexact=extension
            ).first()
            description = self.DESCRIPTION_ANNEXE
            if not format_document:
                self._erreur(
                    f"[DOSSIER DM {numero_dm}] Annexe '{titre_source}' ignorée : "
                    f"format documentaire '{extension or 'sans extension'}' introuvable."
                )
                return "erreurs"

        document_existant = None
        if pj_dm_id is not None:
            document_existant = Document.objects.filter(pj_dm_id=pj_dm_id).first()
        if not document_existant:
            document_existant = Document.objects.filter(url_dm=url).first()

        if document_existant:
            deja_lie = DossierManifSportiveDocument.objects.filter(
                id_dossier_manif_sportive=dossier,
                id_document=document_existant,
            ).exists()
            detail_liaison = "déjà lié au dossier" if deja_lie else "non lié à ce dossier"
            identifiant_existant = (
                f"PJ DM {pj_dm_id}"
                if pj_dm_id is not None
                else "PJ avis sans identifiant API"
            )
            self._avertissement(
                f"[DOSSIER DM {numero_dm}] {identifiant_existant} '{titre_source}' déjà "
                f"présente comme Document {document_existant.id} ({detail_liaison}) : ignorée."
            )
            return "deja_presentes"

        document_meme_numero = None
        if est_arrete:
            document_meme_numero = Document.objects.filter(
                id_nature=nature_arrete,
                numero=numero_document,
            ).first()
        if est_arrete and document_meme_numero:
            self._erreur(
                f"[DOSSIER DM {numero_dm}] Bancarisation refusée pour '{titre_source}' : "
                f"le numéro d'arrêté {numero_document} est déjà porté par le Document "
                f"{document_meme_numero.id} "
                f"('{document_meme_numero.emplacement}{document_meme_numero.titre}'). "
                "Aucune donnée et aucun fichier ne sont créés pour cette pièce."
            )
            return "erreurs"

        piece_meme_numero = self.numeros_planifies.get(numero_document) if est_arrete else None
        if est_arrete and piece_meme_numero:
            if piece_meme_numero["numero_dm"] == numero_dm:
                self._avertissement(
                    f"[DOSSIER DM {numero_dm}] Ancienne version '{titre_source}' "
                    f"ignorée : le numéro {numero_document} a déjà été retenu depuis "
                    f"un avis plus récent avec '{piece_meme_numero['titre']}'."
                )
                return "ignorees"
            else:
                self._erreur(
                    f"[DOSSIER DM {numero_dm}] Bancarisation refusée pour "
                    f"'{titre_source}' : le numéro d'arrêté {numero_document} est "
                    f"déjà prévu dans ce lot pour le dossier DM "
                    f"{piece_meme_numero['numero_dm']} "
                    f"('{piece_meme_numero['titre']}'). Aucune donnée et aucun fichier "
                    "ne sont créés pour cette pièce."
                )
                return "erreurs"

        if est_arrete:
            self.numeros_planifies[numero_document] = {
                "numero_dm": numero_dm,
                "titre": titre_source,
            }

        emplacement = Document.normaliser_emplacement(
            os.path.join(dossier.emplacement, self.SOUS_DOSSIER)
        )
        titre = get_nom_disponible(emplacement, titre_source) if nas_root else titre_source
        date_document, origine_date = self._date_document(pj, avis)

        identifiant_pj = f"PJ DM {pj_dm_id}" if pj_dm_id is not None else "PJ avis sans identifiant API"
        self._trace(
            f"[DOSSIER DM {numero_dm}] {identifiant_pj} '{titre_source}' -> "
            f"'{emplacement}{titre}', nature='{nature_document.nature}', "
            f"format='{format_document.format}', numéro="
            f"'{numero_document or ''}', date={date_document.isoformat()} "
            f"({origine_date})."
        )

        if not execute:
            return "a_bancariser"

        try:
            contenu = self._telecharger_fichier(token, url)
        except Exception as exc:
            self._erreur(
                f"[DOSSIER DM {numero_dm}] Échec du téléchargement de "
                f"'{titre_source}' : {exc}"
            )
            return "erreurs"

        chemin_nas = os.path.join(nas_root, emplacement, titre)
        if not ecrire_file_sur_nas(contenu, chemin_nas):
            self._erreur(
                f"[DOSSIER DM {numero_dm}] Échec de l'écriture NAS de '{chemin_nas}'."
            )
            return "erreurs"

        try:
            with transaction.atomic():
                document = Document.objects.create(
                    id_format=format_document,
                    id_nature=nature_document,
                    url_dm=url,
                    emplacement=emplacement,
                    description=description,
                    numero=numero_document,
                    titre=titre,
                    date=date_document,
                    pj_dm_id=pj_dm_id,
                )
                # Lors de la première sauvegarde, Document.save() considère la
                # nature comme changée (None -> Arrêté directeur) et applique la
                # numérotation automatique. Cette commande de reprise doit ensuite
                # restaurer le numéro officiel déjà porté par l'acte DM.
                if est_arrete and document.numero != numero_document:
                    document.numero = numero_document
                    document.save(update_fields=["numero"])
                DossierManifSportiveDocument.objects.create(
                    id_dossier_manif_sportive=dossier,
                    id_document=document,
                )
        except Exception as exc:
            try:
                if smbclient.path.exists(chemin_nas):
                    smbclient.remove(chemin_nas)
            except Exception as nettoyage_exc:
                self._erreur(
                    f"[DOSSIER DM {numero_dm}] Échec du nettoyage du fichier NAS "
                    f"après erreur BDD : {nettoyage_exc}"
                )
            self._erreur(
                f"[DOSSIER DM {numero_dm}] Fichier téléchargé mais création BDD annulée "
                f"pour PJ DM {pj_dm_id} : {exc}"
            )
            return "erreurs"

        self._trace(
            f"[DOSSIER DM {numero_dm}] Document {document.id} créé et lié au dossier ; "
            f"nature={nature_document.nature}, numéro={document.numero or 'vide'}, "
            f"fichier='{emplacement}{titre}'."
        )
        return "bancarisees"

    @staticmethod
    def _extraire_numero_acte(titre):
        correspondance = re.match(
            r"^DIR-I-(\d{4}-\d+)(?:\D|$)",
            titre,
            flags=re.IGNORECASE,
        )
        if correspondance:
            return correspondance.group(1)

        # Certains actes historiques ne portent que le compteur après DIR-I-.
        correspondance_historique = re.match(
            r"^DIR-I-(\d+)(?:\D|$)",
            titre,
            flags=re.IGNORECASE,
        )
        return correspondance_historique.group(1) if correspondance_historique else None

    @staticmethod
    def _date_tri_avis(avis):
        date_avis = avis.date_reponse or avis.date_demande
        return date_avis.timestamp() if date_avis else float("-inf")

    @staticmethod
    def _date_document(pj, avis):
        for cle in ("date_televersement", "date_modification_model"):
            valeur = parse_datetime_with_tz(pj.get(cle))
            if valeur:
                return valeur, cle
        if avis.date_reponse:
            return avis.date_reponse, "date de réponse de l'avis (repli)"
        return timezone.now(), "date courante (repli)"

    @staticmethod
    def _telecharger_fichier(token, url):
        # Une URL absolue est conservée telle quelle : un test sur la préproduction
        # ne doit jamais être redirigé silencieusement vers le serveur de production.
        url_complete = url if url.startswith(("http://", "https://")) else urljoin(API_URL, url)
        reponse = SESSION.get(
            url_complete,
            headers={"Authorization": f"Bearer {token}"},
            timeout=(5, 60),
        )
        reponse.raise_for_status()
        return reponse.content

    def _trace(self, message):
        self.stdout.write(message)
        logger.info("[BANCARISATION ACTES DM] %s", message)

    def _avertissement(self, message):
        self.stdout.write(self.style.WARNING(message))
        logger.warning("[BANCARISATION ACTES DM] %s", message)

    def _erreur(self, message):
        self.stderr.write(self.style.ERROR(message))
        logger.error("[BANCARISATION ACTES DM] %s", message)
