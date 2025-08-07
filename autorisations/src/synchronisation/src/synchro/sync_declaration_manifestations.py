from datetime import date, datetime
import json
import logging
from django.db import models

from autorisations.models.models_instruction import DossierManifSportive, DossierManifestationLiaison
from synchronisation.src.utils.fichiers import create_emplacement_sport, write_geojson
from synchronisation.src.utils.model_helpers import foreign_keys_add_suffixe_id, update_fields




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

    try:
        defaults = foreign_keys_add_suffixe_id(DossierManifSportive, dossier)
    except Exception as e:
        logger.error(f"Erreur lors du foreign_keys_add_suffixe_id DossierManifSportive : {e}")
        return None


    try:
        obj, created = DossierManifSportive.objects.get_or_create(
            numero_dossier_declaration_manifestations=int(dossier["numero_dossier_declaration_manifestations"]),
            defaults=defaults
        )
    except Exception as e:
        logger.error(f"Erreur lors du get_or_create DossierManifSportive : {e}")
        return None


    if created:
        logger.info(f"[CREATE] DossierManifSportive numéro {obj.numero_dossier_declaration_manifestations} ({obj.nom_dossier}).")

        # Si le dossier DM est déjà lié à un dossier DS
        liaison_existe = DossierManifestationLiaison.objects.filter(
                    id_dossier_manif=obj.id
                ).exists()
        
        if liaison_existe :
                logger.error(f"DossierManifSportive numéro {obj.numero_dossier_declaration_manifestations} apparait en création alors qu'il est déjà lié à un dossier DS")
        else:
            #  -->  Dossier DS en attente
            create_emplacement_sport(obj, logger)

        # Write geojson
        if obj.geometrie :
            write_geojson(f"{obj.emplacement}", f"{obj.numero_dossier_declaration_manifestations}.geojson", obj.geometrie)
        else :
            logger.warning(f"[CREATE] DossierManifSportive numéro {obj.numero_dossier_declaration_manifestations} : Aucune géométrie récupérée")

        logger.info("")
            
    else:
        update_data = {}

        for field, new_value in dossier.items():
            model_field = getattr(obj.__class__, field, None)
            field_name = f"{field}_id" if isinstance(getattr(model_field, 'field', None), models.ForeignKey) else field

            # Ignore geometrie vide
            if field == "geometrie" and not new_value:
                continue

            update_data[field_name] = new_value if isinstance(new_value, (date, datetime)) else new_value

        updated_fields = update_fields(
            obj,
            update_data,
            date_fields=[k for k, v in dossier.items() if isinstance(v, (date, datetime))]
        )

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] DossierManifSportive {obj.numero_dossier_declaration_manifestations} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
            logger.info("")
            if "geometrie" in updated_fields :
                # Write geojson
                write_geojson(f"{obj.emplacement}", f"{obj.numero_dossier_declaration_manifestations}.geojson",obj.geometrie)
        else:
            logger.info(f"[NO CHANGE] DossierManifSportive {obj.numero_dossier_declaration_manifestations} inchangé.")


    return obj.id
