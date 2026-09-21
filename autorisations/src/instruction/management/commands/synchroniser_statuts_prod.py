from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from autorisations.models.models_instruction import (
    Dossier,
    DossierManifSportive,
    EtapeDossier,
    EtatDossier,
)


class Command(BaseCommand):
    help = (
        "Compare les statuts des dossiers de production avec ceux de "
        "développement, sans effectuer de modification."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--details",
            action="store_true",
            help="Affiche le détail de chaque dossier qui serait modifié.",
        )
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Applique les modifications uniquement dans la BDD de développement.",
        )

    def handle(self, *args, **options):
        self._verifier_environnement()

        snapshots_dn = self._charger_vue(
            """
            SELECT
                numero,
                etape,
                etat,
                present_sur_ds,
                date_debut_instruction,
                date_fin_instruction
            FROM maintenance.v_miroir_statuts_dossiers_dn
            """
        )
        snapshots_dm = self._charger_vue(
            """
            SELECT numero, etape, etat_dossier, archive
            FROM maintenance.v_miroir_statuts_dossiers_dm
            """
        )

        bilan_dn = self._comparer_dossiers_dn(snapshots_dn, options["details"])
        bilan_dm = self._comparer_dossiers_dm(snapshots_dm, options["details"])

        erreurs = bilan_dn["erreurs"] + bilan_dm["erreurs"]
        if erreurs:
            self.stdout.write("")
            self.stdout.write(self.style.MIGRATE_HEADING("Bilan du dry-run"))
            self._afficher_bilan("Dossiers DN", bilan_dn)
            self._afficher_bilan("Dossiers DM", bilan_dm)
            raise CommandError(
                "Le contrôle contient des erreurs bloquantes. Aucune donnée n'a été modifiée."
            )

        if options["execute"]:
            self._verifier_cible_developpement()
            self._appliquer_mises_a_jour(bilan_dn, bilan_dm)

        self.stdout.write("")
        titre_bilan = "Bilan de la synchronisation" if options["execute"] else "Bilan du dry-run"
        self.stdout.write(self.style.MIGRATE_HEADING(titre_bilan))
        self._afficher_bilan("Dossiers DN", bilan_dn)
        self._afficher_bilan("Dossiers DM", bilan_dm)
        self.stdout.write("")
        if options["execute"]:
            self.stdout.write(
                self.style.SUCCESS(
                    "Synchronisation appliquée dans la BDD de développement uniquement."
                )
            )
        else:
            self.stdout.write(
                self.style.WARNING(
                    "Aucune donnée n'a été modifiée. Utilisez --execute après validation du dry-run."
                )
            )

    def _verifier_environnement(self):
        if settings.ENVIRONMENT != "dev":
            raise CommandError("Cette commande est réservée à l'environnement de développement.")

        if "prod_readonly" not in settings.DATABASES:
            raise CommandError(
                "La connexion 'prod_readonly' n'est pas configurée. "
                "Renseignez toutes les variables BDD_PROD_READONLY_* dans .env.dev."
            )

        default = settings.DATABASES["default"]
        production = settings.DATABASES["prod_readonly"]
        identite_default = (
            default.get("HOST"),
            str(default.get("PORT")),
            default.get("NAME"),
        )
        identite_production = (
            production.get("HOST"),
            str(production.get("PORT")),
            production.get("NAME"),
        )
        if identite_default == identite_production:
            raise CommandError(
                "Les connexions 'default' et 'prod_readonly' ciblent la même base. "
                "Synchronisation refusée."
            )

        with connections["prod_readonly"].cursor() as cursor:
            cursor.execute("SHOW transaction_read_only")
            lecture_seule = cursor.fetchone()[0]
            if lecture_seule != "on":
                raise CommandError(
                    "La connexion de production n'est pas en lecture seule. Synchronisation refusée."
                )

    def _verifier_cible_developpement(self):
        try:
            with connections["default"].cursor() as cursor:
                cursor.execute(
                    "SELECT environnement FROM maintenance.environnement_agida WHERE id = true"
                )
                ligne = cursor.fetchone()
        except Exception as exc:
            raise CommandError(
                "Marqueur de la BDD de développement absent ou inaccessible. "
                "Exécutez d'abord docs/sql/2026-09-15_garde_fou_bdd_dev.sql "
                "sur la BDD de développement."
            ) from exc

        if not ligne or ligne[0] != "dev":
            raise CommandError(
                "La BDD cible n'est pas explicitement marquée comme environnement 'dev'. "
                "Synchronisation refusée."
            )

    def _appliquer_mises_a_jour(self, bilan_dn, bilan_dm):
        plans_dn = {plan["id"]: plan for plan in bilan_dn["mises_a_jour"]}
        plans_dm = {plan["id"]: plan for plan in bilan_dm["mises_a_jour"]}

        with transaction.atomic(using="default"):
            dossiers_dn = list(
                Dossier.objects.using("default")
                .select_for_update()
                .filter(id__in=plans_dn)
            )
            dossiers_dm = list(
                DossierManifSportive.objects.using("default")
                .select_for_update()
                .filter(id__in=plans_dm)
            )

            if len(dossiers_dn) != len(plans_dn) or len(dossiers_dm) != len(plans_dm):
                raise CommandError(
                    "Un dossier a disparu entre le contrôle et l'écriture. Transaction annulée."
                )

            for dossier in dossiers_dn:
                valeurs = plans_dn[dossier.id]
                dossier.id_etape_dossier_id = valeurs["id_etape_dossier_id"]
                dossier.id_etat_dossier_id = valeurs["id_etat_dossier_id"]
                dossier.present_sur_ds = valeurs["present_sur_ds"]
                dossier.date_debut_instruction = valeurs["date_debut_instruction"]
                dossier.date_fin_instruction = valeurs["date_fin_instruction"]

            for dossier in dossiers_dm:
                valeurs = plans_dm[dossier.id]
                dossier.id_etape_id = valeurs["id_etape_id"]
                dossier.etat_dossier = valeurs["etat_dossier"]
                dossier.archive = valeurs["archive"]

            if dossiers_dn:
                Dossier.objects.using("default").bulk_update(
                    dossiers_dn,
                    [
                        "id_etape_dossier",
                        "id_etat_dossier",
                        "present_sur_ds",
                        "date_debut_instruction",
                        "date_fin_instruction",
                    ],
                )
            if dossiers_dm:
                DossierManifSportive.objects.using("default").bulk_update(
                    dossiers_dm,
                    ["id_etape", "etat_dossier", "archive"],
                )

    def _charger_vue(self, requete):
        with connections["prod_readonly"].cursor() as cursor:
            cursor.execute(requete)
            colonnes = [colonne[0] for colonne in cursor.description]
            return [dict(zip(colonnes, ligne)) for ligne in cursor.fetchall()]

    def _comparer_dossiers_dn(self, snapshots, details):
        dossiers_dev = {
            dossier.numero: dossier
            for dossier in Dossier.objects.filter(
                numero__in=[snapshot["numero"] for snapshot in snapshots]
            ).select_related("id_etape_dossier", "id_etat_dossier")
        }
        etapes_dev = {etape.etape: etape for etape in EtapeDossier.objects.all()}
        etats_dev = {etat.nom: etat for etat in EtatDossier.objects.all()}
        bilan = self._nouveau_bilan(len(snapshots), len(dossiers_dev))

        for snapshot in snapshots:
            dossier = dossiers_dev.get(snapshot["numero"])
            if not dossier:
                continue

            if snapshot["etape"] not in etapes_dev:
                self._ajouter_erreur(
                    bilan,
                    f"DN {dossier.numero} : étape inconnue en dev '{snapshot['etape']}'",
                )
                continue
            if snapshot["etat"] not in etats_dev:
                self._ajouter_erreur(
                    bilan,
                    f"DN {dossier.numero} : état inconnu en dev '{snapshot['etat']}'",
                )
                continue

            changements = self._differences(
                {
                    "etape": dossier.id_etape_dossier.etape,
                    "etat": dossier.id_etat_dossier.nom,
                    "present_sur_ds": dossier.present_sur_ds,
                    "date_debut_instruction": dossier.date_debut_instruction,
                    "date_fin_instruction": dossier.date_fin_instruction,
                },
                snapshot,
            )
            self._enregistrer_comparaison(bilan, "DN", dossier.numero, changements, details)
            if changements:
                bilan["mises_a_jour"].append({
                    "id": dossier.id,
                    "id_etape_dossier_id": etapes_dev[snapshot["etape"]].id,
                    "id_etat_dossier_id": etats_dev[snapshot["etat"]].id,
                    "present_sur_ds": snapshot["present_sur_ds"],
                    "date_debut_instruction": snapshot["date_debut_instruction"],
                    "date_fin_instruction": snapshot["date_fin_instruction"],
                })

        return bilan

    def _comparer_dossiers_dm(self, snapshots, details):
        dossiers_dev = {
            dossier.numero_dossier_declaration_manifestations: dossier
            for dossier in DossierManifSportive.objects.filter(
                numero_dossier_declaration_manifestations__in=[
                    snapshot["numero"] for snapshot in snapshots
                ]
            ).select_related("id_etape")
        }
        etapes_dev = {etape.etape: etape for etape in EtapeDossier.objects.all()}
        bilan = self._nouveau_bilan(len(snapshots), len(dossiers_dev))

        for snapshot in snapshots:
            dossier = dossiers_dev.get(snapshot["numero"])
            if not dossier:
                continue

            if snapshot["etape"] not in etapes_dev:
                self._ajouter_erreur(
                    bilan,
                    f"DM {dossier.numero_dossier_declaration_manifestations} : "
                    f"étape inconnue en dev '{snapshot['etape']}'",
                )
                continue

            changements = self._differences(
                {
                    "etape": dossier.id_etape.etape,
                    "etat_dossier": dossier.etat_dossier,
                    "archive": dossier.archive,
                },
                snapshot,
            )
            self._enregistrer_comparaison(
                bilan,
                "DM",
                dossier.numero_dossier_declaration_manifestations,
                changements,
                details,
            )
            if changements:
                bilan["mises_a_jour"].append({
                    "id": dossier.id,
                    "id_etape_id": etapes_dev[snapshot["etape"]].id,
                    "etat_dossier": snapshot["etat_dossier"],
                    "archive": snapshot["archive"],
                })

        return bilan

    @staticmethod
    def _differences(valeurs_dev, snapshot_prod):
        return {
            champ: (valeur_dev, snapshot_prod[champ])
            for champ, valeur_dev in valeurs_dev.items()
            if valeur_dev != snapshot_prod[champ]
        }

    @staticmethod
    def _nouveau_bilan(nombre_prod, nombre_dev):
        return {
            "lus_prod": nombre_prod,
            "presents_dev": nombre_dev,
            "a_modifier": 0,
            "inchanges": 0,
            "erreurs": [],
            "mises_a_jour": [],
        }

    def _enregistrer_comparaison(self, bilan, type_dossier, numero, changements, details):
        if not changements:
            bilan["inchanges"] += 1
            return

        bilan["a_modifier"] += 1
        if details:
            resume = "; ".join(
                f"{champ}: {ancien!r} -> {nouveau!r}"
                for champ, (ancien, nouveau) in changements.items()
            )
            self.stdout.write(f"[{type_dossier} {numero}] {resume}")

    def _ajouter_erreur(self, bilan, message):
        bilan["erreurs"].append(message)
        self.stderr.write(self.style.ERROR(message))

    def _afficher_bilan(self, libelle, bilan):
        absents_dev = bilan["lus_prod"] - bilan["presents_dev"]
        self.stdout.write(
            f"{libelle} : {bilan['lus_prod']} lus en production, "
            f"{bilan['presents_dev']} présents en dev, "
            f"{absents_dev} absents de dev, "
            f"{bilan['a_modifier']} à modifier, "
            f"{bilan['inchanges']} inchangés, "
            f"{len(bilan['erreurs'])} erreur(s)."
        )
