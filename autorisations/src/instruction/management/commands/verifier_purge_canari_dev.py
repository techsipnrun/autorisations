import hashlib
import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from autorisations.models.models_instruction import Dossier
from instruction.management.commands.inventorier_purge_dev import (
    Command as CommandeInventaire,
    ETAPES_TERMINEES,
)


class Command(BaseCommand):
    help = (
        "Vérifie sans aucune modification qu'une unité DN d'un manifeste "
        "peut servir de canari pour la purge DEV."
    )

    def add_arguments(self, parser):
        parser.add_argument("--manifeste", required=True, help="Chemin du manifeste JSON.")
        parser.add_argument("--numero", required=True, help="Numéro DN exact à vérifier.")

    def handle(self, *args, **options):
        inventaire = CommandeInventaire()
        inventaire._verifier_cible_developpement()

        chemin_manifeste = Path(options["manifeste"]).expanduser().resolve()
        manifeste = self._charger_et_verifier_manifeste(chemin_manifeste)
        numero = str(options["numero"]).strip()
        correspondances = [
            unite
            for unite in manifeste.get("unites", [])
            if unite.get("type") == "DN" and str(unite.get("numero")) == numero
        ]
        if len(correspondances) != 1:
            raise CommandError(
                f"Le manifeste doit contenir exactement une unité DN {numero}."
            )
        unite = correspondances[0]
        if unite.get("avis") != 0:
            raise CommandError("Le premier canari doit être un dossier DN sans avis.")
        if unite.get("documents_partages") != 0:
            raise CommandError("Le dossier comporte des documents partagés.")
        if unite.get("erreur_nas"):
            raise CommandError("Le manifeste contient une erreur NAS pour ce dossier.")

        ids_dn = unite.get("ids_dn") or []
        if len(ids_dn) != 1 or unite.get("ids_dm"):
            raise CommandError("L'unité choisie n'est pas un dossier DN seul.")
        try:
            dossier = Dossier.objects.using("default").select_related(
                "id_etape_dossier"
            ).get(pk=ids_dn[0], numero=int(numero))
        except (Dossier.DoesNotExist, ValueError) as exc:
            raise CommandError("Le dossier DN du manifeste n'existe plus en BDD.") from exc

        if dossier.id_etape_dossier.etape not in ETAPES_TERMINEES:
            raise CommandError("Le dossier n'est plus dans une étape terminale.")
        emplacements = unite.get("emplacements") or []
        emplacement_actuel = inventaire._normaliser_chemin_relatif(dossier.emplacement)
        if len(emplacements) != 1 or (
            inventaire._normaliser_chemin_relatif(emplacements[0]) != emplacement_actuel
        ):
            raise CommandError("L'emplacement NAS du dossier a changé depuis le manifeste.")

        activite = inventaire._activites_dn([dossier]).get(dossier.id)
        if not activite or activite.isoformat() != unite.get("derniere_activite"):
            raise CommandError("L'activité du dossier a changé depuis le manifeste.")
        statistiques = inventaire._statistiques_bdd([dossier.id], [])
        for champ in (
            "messages", "avis", "avis_partages", "documents", "documents_partages",
            "actions", "notes", "mails",
        ):
            if statistiques[champ] != unite.get(champ):
                raise CommandError(
                    f"La valeur {champ} a changé : manifeste={unite.get(champ)}, "
                    f"BDD={statistiques[champ]}."
                )

        taille = inventaire._taille_repertoire_nas(dossier.emplacement)
        if taille != unite.get("taille_nas_octets"):
            raise CommandError(
                "Le contenu NAS a changé : "
                f"manifeste={inventaire._taille_lisible(unite.get('taille_nas_octets'))}, "
                f"NAS={inventaire._taille_lisible(taille)}."
            )

        self.stdout.write(self.style.SUCCESS(f"Canari DN {numero} vérifié."))
        self.stdout.write(f"Étape : {dossier.id_etape_dossier.etape}")
        self.stdout.write(f"Emplacement : {dossier.emplacement}")
        self.stdout.write(f"Taille NAS : {inventaire._taille_lisible(taille)}")
        self.stdout.write(f"Documents : {statistiques['documents']}")
        self.stdout.write("Aucune donnée BDD et aucun fichier NAS n'ont été modifiés.")

    def _charger_et_verifier_manifeste(self, chemin):
        if not chemin.is_file():
            raise CommandError(f"Manifeste introuvable : {chemin}")
        empreinte = self._sha256(chemin)
        fichier_empreinte = chemin.with_suffix(".json.sha256")
        if not fichier_empreinte.is_file():
            raise CommandError("Fichier SHA-256 du manifeste introuvable.")
        attendu = fichier_empreinte.read_text(encoding="utf-8").split()[0]
        if empreinte != attendu:
            raise CommandError("L'empreinte SHA-256 du manifeste est invalide.")

        try:
            manifeste = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise CommandError("Le manifeste JSON est illisible.") from exc
        if manifeste.get("environnement") != "dev" or manifeste.get("version") != 1:
            raise CommandError("Manifeste incompatible ou non destiné au DEV.")

        sauvegarde = manifeste.get("sauvegarde_bdd") or {}
        archive = Path(sauvegarde.get("chemin", "")).expanduser()
        if not archive.is_file() or self._sha256(archive) != sauvegarde.get("sha256"):
            raise CommandError("La sauvegarde BDD associée est absente ou altérée.")

        unites = manifeste.get("unites") or []
        canonique = json.dumps(
            unites, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(canonique).hexdigest() != manifeste.get("selection_sha256"):
            raise CommandError("La sélection contenue dans le manifeste est altérée.")
        return manifeste

    @staticmethod
    def _sha256(chemin):
        empreinte = hashlib.sha256()
        with chemin.open("rb") as fichier:
            for bloc in iter(lambda: fichier.read(1024 * 1024), b""):
                empreinte.update(bloc)
        return empreinte.hexdigest()
