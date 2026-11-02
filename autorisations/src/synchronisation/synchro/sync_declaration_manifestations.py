from datetime import date, datetime, timedelta
import hashlib
import json
import logging
import os
import smbclient
from django.db import connection, models
from django.utils import timezone
from autorisations.utils.nas_fonctions import _normalize_unc_path

from autorisations.models.models_instruction import Champ, Dossier, DossierManifSportive, DossierManifestationLiaison
from instruction.utils.carto_utils import intersecte_coeur_de_parc
from instruction.utils.files_utils import load_geojson
from instruction.utils.utilisateurs_utils import envoi_auto_mail_relance
from synchronisation.utils.fichiers import construire_emplacement_manif_sportive, create_emplacement, create_emplacement_manif_sportive, nettoyer_nom_fichier, write_geojson
from synchronisation.utils.model_helpers import foreign_keys_add_suffixe_id, update_fields


CHAMPS_IDENTITE_DM = {
    "nom_organisateur",
    "prenom_organisateur",
    "nom_contact",
    "prenom_contact",
    "nom_coordinateur_securite",
    "prenom_coordinateur_securite",
}
DATE_LIMITE_IDENTITES_ANONYMISEES_DM = date(2025, 8, 1)


def _choisir_emplacement_nouveau_dm(nom_manifestation, date_reception):
    """Réserve un nom libre via la transaction de création de get_or_create."""
    base = construire_emplacement_manif_sportive(nom_manifestation, date_reception).rstrip("/")
    racine = os.environ["NAS_ROOT"]
    if connection.vendor == "postgresql":
        # Sérialiser les créations d'une même racine annuelle : les noms
        # « trail » et « trail_2 » peuvent se croiser via les suffixes.
        # Le chemin enregistré en BDD réserve ensuite le nom retenu.
        parent = base.rsplit("/", 1)[0].casefold()
        cle = int.from_bytes(hashlib.sha256(parent.encode()).digest()[:4], "big", signed=True)
        with connection.cursor() as curseur:
            curseur.execute("SELECT pg_advisory_xact_lock(%s, %s)", [0x444D4E41, cle])
    indice = 1
    while True:
        candidat = f"{base}{'_' + str(indice) if indice > 1 else ''}/"
        utilise_en_bdd = DossierManifSportive.objects.filter(emplacement__iexact=candidat).exists()
        if not utilise_en_bdd and not smbclient.path.exists(_normalize_unc_path(os.path.join(racine, candidat))):
            return candidat
        indice += 1


def doit_preserver_identite_anonymisee(dossier):
    """Indique si les champs vidés après anonymisation DM doivent le rester."""
    date_depot = dossier.date_depot
    if isinstance(date_depot, datetime):
        date_depot = date_depot.date()

    return bool(
        dossier.archive
        and date_depot
        and date_depot < DATE_LIMITE_IDENTITES_ANONYMISEES_DM
        and all(getattr(dossier, champ) is None for champ in CHAMPS_IDENTITE_DM)
    )




def sync_declaration_manifestations(dossier, logger, dico_notifs={}, *, date_reception=None):
    """
    Synchronise un objet DossierManifSportive à partir des données de déclaration-manifestations.
    date_reception est la dernière demande d'avis connue pour le Parc ; elle
    sert uniquement à initialiser le chemin NAS d'un dossier encore absent.

     {
                "nom_organisateur","prenom_organisateur","qualite_declarant","structure","adresse","numero_telephone","email_structure",

                "nom_dossier","numero_dossier_declaration_manifestations","etat_dossier","date_depot","date_debut_evenement","date_fin_evenement","emprise_voie_publique",
                "evenement_competition","description","observation","activite","affilie_federation_delegataire","nombre_participants","nombre_max_spectateurs",
                "nombre_organisateurs","nombre_vehicules_accompagnement","depart_groupe_participants","circulation_groupee_participants",

                "respect_code_route","priorite_passage","usage_exclusif_temporaire_chaussee","usage_privatif_chaussee","precisions_voies_et_horaires",

                "vehicule_ouverture","vehicule_tete_course","vehicule_fin_course","autres_vehicules_organisation","nombre_signaleurs","signaleurs_mobiles_voitures",
                "signaleurs_mobiles_motos","encadrement_police_municipale","details_encadrement_police_municipale","convention_police_nationale",
                "details_convention_police_nationale",

                "nom_coordinateur_securite","prenom_coordinateur_securite","telephone_coordinateur_securite","email_coordinateur_securite",

                "nom_contact","prenom_contact","telephone_contact","autres_contacts_utiles",

                "budget_depasse_100k","manifestation_lucrative_plus_1500","manifestation_titre_national_international","manifestation_vehicules_hors_voies_ouvertes",
                "charte_dispense_natura_2000","lieux_pdesi",

                "signataire_charte_balisage","description_balisage",

                "geometrie"
            }
    """
    # Exemple : Manifestations_sportives/2026/Declaration Manifestations/trail/

    manif_id = int(dossier["numero_dossier_declaration_manifestations"])
    champ_num_dm = Champ.objects.get(nom="Numéro du dossier sur la plateforme déclaration-manifestations")
    nom_courses_clean = nettoyer_nom_fichier(dossier.get('nom_dossier'))
    dossier_dn = None
    doss_lie = False

    try:
        defaults = foreign_keys_add_suffixe_id(DossierManifSportive, dossier)
        # Django n'évalue ce callable que si le dossier n'existe pas encore.
        # Les emplacements historiques ne sont ni recalculés ni déplacés.
        defaults["emplacement"] = lambda: _choisir_emplacement_nouveau_dm(
            dossier.get("nom_dossier"), date_reception,
        )
    except Exception as e:
        logger.error(f"Erreur lors du foreign_keys_add_suffixe_id DossierManifSportive : {e}")
        return None


    try:
        obj, created = DossierManifSportive.objects.get_or_create(numero_dossier_declaration_manifestations=manif_id, defaults=defaults)
    except Exception as e:
        logger.error(f"Erreur lors du get_or_create DossierManifSportive : {e}")
        return None

    """
    Pour info :
    Si obj.etat_dossier = caduc ou obj.etat_dossier = termine :
        On peut quand meme rendre un avis sur DM.
    """

    # ----------------------------
    # NOUVEAU DossierManifSportive
    # ----------------------------
    if created:
        logger.info(f"[CREATE] DossierManifSportive numéro {manif_id} ({obj.nom_dossier}).")

        # CALCUL INTERSECTION COEUR DE PARC
        if obj.coeur_de_parc is None :
            coeur_geojson = load_geojson("instruction/static/instruction/carto/fond_coeur_de_parc.geojson")

            obj.coeur_de_parc = intersecte_coeur_de_parc(obj.geometrie, coeur_geojson)
            obj.save(update_fields=["coeur_de_parc"])
            # Mail de relance envoyé depuis la Réception
  

        #On regarde si un dossier DN (de - d'un an, non lié, non archivé) existe deja pour cette manifestation
        dossier_dn = (
            Dossier.objects
            .filter(
                id_demarche__type__iexact="Manifestations sportives",
                date_depot__gte=timezone.now() - timedelta(days=365),
                dossierchamp__id_champ=champ_num_dm,
                dossierchamp__valeur=str(manif_id),
                dossiermanifestationliaison__isnull=True,
            )
            .exclude(
                id_etape_dossier__etape__in=[
                    "À publier au RAA",
                    "Non soumis à autorisation",
                    "Refusé",
                    "Accepté",
                ]
            )
            .order_by("-date_depot")
            .first()
        )
        

        if dossier_dn :
            # -------------------------
            # DOSSIER DN RECU AVANT DM (ou alors numéro DM mal renseigné dans le form DN)
            # -------------------------
            logger.warning(f"[CREATE] DossierManifSportive {manif_id} : Dossier Démarche Numérique déjà existant.")

            # Liaison existante
            liaisons_dossDS = DossierManifestationLiaison.objects.filter(id_dossier=dossier_dn)
            if liaisons_dossDS :
                # logger.warning(f"[CREATE DossierManifSportive numéro {manif_id}] Le dossier DN {dossier_dn.numero} est déjà lié à un dossier DM, pour des raisons de cohérence, on supprime la DossierManifestationLiaison.")
                # liaisons_dossDS.delete()
                logger.warning(f"[CREATE DossierManifSportive (DM) numéro {manif_id}] Le dossier DN {dossier_dn.numero} est déjà lié au dossier DM {liaisons_dossDS.id_dossier_manif.numero_dossier_declaration_manifestations}. La liaison ne peut donc pas être faite.")
                return obj, doss_lie
            
            # Création liaison
            liaison, created_liaison = DossierManifestationLiaison.objects.get_or_create(id_dossier_manif=obj,id_dossier=dossier_dn)

            if created_liaison:
                logger.info(f"[CREATE] Liaison créée entre DossierManifSportive {manif_id} et Dossier DN {dossier_dn.numero}.")
                doss_lie = True
                
            # obj.emplacement = dossier_dn.emplacement
            obj.save()


        else:
            # -------------------------
            # DOSSIER DM RECU AVANT DN (cas majoritaire)
            # -------------------------
            # Création des folders

            # emplacement = f"Manifestations_sportives/2026/Declaration Manifestations/NomManif/"
            create_emplacement_manif_sportive(obj.emplacement)

        # Write geojson
        if obj.geometrie :
            write_geojson(f"{obj.emplacement}/Carto/", f"{nom_courses_clean}.geojson", obj.geometrie)
        else :
            logger.warning(f"[CREATE] DossierManifSportive numéro {manif_id} : Aucune géométrie récupérée")


        #######################
        # NOTIFICATION PAR MAIL 
        #######################
        type_demarche = "Manifestations sportives (Déclaration Manifestations)"
        if type_demarche in dico_notifs:
            dico_notifs[type_demarche] += 1
        else:
            dico_notifs[type_demarche] = 1



    # -----------------------------
    # DossierManifSportive EXISTANT 
    # -----------------------------
    else:
        update_data = {}

        doss_lie = DossierManifestationLiaison.objects.filter(id_dossier_manif=obj).exists()

        champs_a_preserver = (
            CHAMPS_IDENTITE_DM if doit_preserver_identite_anonymisee(obj) else set()
        )
        if champs_a_preserver:
            logger.info(
                f"[DOSSIER DM {manif_id}] Identité anonymisée conservée vide "
                "(dossier archivé déposé avant août 2025)."
            )

        for field, new_value in dossier.items():

            # On ne met pas à jour l'emplacement
            if field == "emplacement" or field in champs_a_preserver:
                continue
            
            # Ignore geometrie vide
            if field == "geometrie" and not new_value :
                continue
    


            model_field = getattr(obj.__class__, field, None)
            field_name = f"{field}_id" if isinstance(getattr(model_field, 'field', None), models.ForeignKey) else field


            update_data[field_name] = new_value if isinstance(new_value, (date, datetime)) else new_value

        updated_fields = update_fields(
            obj,
            update_data,
            date_fields=[k for k, v in dossier.items() if isinstance(v, (date, datetime))]
        )

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] DossierManifSportive {manif_id} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")

            if "geometrie" in updated_fields :
                # Write geojson
                write_geojson(f"{obj.emplacement}/Carto/", f"{nom_courses_clean}.geojson",obj.geometrie)
                logger.warning("GEOMETRIE MODIFIÉE PAR L'ORGANISATEUR SUR DM, IL FAUT RECALCULER LA VALEUR coeur_de_parc")


        else:
            logger.info(f"[NO CHANGE] DossierManifSportive {manif_id} inchangé.")


    return obj, doss_lie
