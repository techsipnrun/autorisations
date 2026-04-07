from datetime import date, datetime, timedelta
import json
import logging
from django.db import models
from django.utils import timezone

from autorisations.models.models_instruction import Champ, Dossier, DossierManifSportive, DossierManifestationLiaison
from synchronisation.utils.fichiers import create_emplacement, create_emplacement_manif_sportive, nettoyer_nom_fichier, write_geojson
from synchronisation.utils.model_helpers import foreign_keys_add_suffixe_id, update_fields




def sync_declaration_manifestations(dossier, logger):
    """
    Synchronise un objet DossierManifSportive à partir des données de déclaration-manifestations.

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

                "geometrie","emplacement"
            }
    """
    # Exemple emplacement : f"Manifestations_sportives/2026/le_grand_trail_de_louest"

    manif_id = int(dossier["numero_dossier_declaration_manifestations"])
    champ_num_dm = Champ.objects.get(nom="Numéro du dossier sur la plateforme déclaration-manifestations")
    nom_courses_clean = nettoyer_nom_fichier(dossier.get('nom_dossier'))
    dossier_dn = None
    doss_lie = False

    try:
        defaults = foreign_keys_add_suffixe_id(DossierManifSportive, dossier)
    except Exception as e:
        logger.error(f"Erreur lors du foreign_keys_add_suffixe_id DossierManifSportive : {e}")
        return None


    try:
        obj, created = DossierManifSportive.objects.get_or_create(numero_dossier_declaration_manifestations=manif_id, defaults=defaults)
    except Exception as e:
        logger.error(f"Erreur lors du get_or_create DossierManifSportive : {e}")
        return None


    # ----------------------------
    # NOUVEAU DossierManifSportive
    # ----------------------------
    if created:
        logger.info(f"[CREATE] DossierManifSportive numéro {manif_id} ({obj.nom_dossier}).")

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
                

            obj.emplacement = dossier_dn.emplacement
            obj.save()


        else:
            # -------------------------
            # DOSSIER DM RECU AVANT DN (cas majoritaire)
            # -------------------------
            # Création des folders
            create_emplacement_manif_sportive(obj.emplacement)

        # Write geojson
        if obj.geometrie :
            write_geojson(f"{obj.emplacement}/Carto/", f"{nom_courses_clean}.geojson", obj.geometrie)
        else :
            logger.warning(f"[CREATE] DossierManifSportive numéro {manif_id} : Aucune géométrie récupérée")



    # -----------------------------
    # DossierManifSportive EXISTANT 
    # -----------------------------
    else:
        update_data = {}

        doss_lie = DossierManifestationLiaison.objects.filter(id_dossier_manif=obj).exists()

        for field, new_value in dossier.items():

            # On ne met pas à jour l'emplacement
            if field == "emplacement":
                continue
            
            # Ignore geometrie vide
            if field == "geometrie" and not new_value:
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
        else:
            logger.info(f"[NO CHANGE] DossierManifSportive {manif_id} inchangé.")


    return obj, doss_lie
