from datetime import date, datetime
from django.utils import timezone
from zoneinfo import ZoneInfo

import json
import logging
from django.db import models

from autorisations.models.models_instruction import AvisManifSportive, DossierManifSportive, DossierManifestationLiaison
from synchronisation.utils.model_helpers import update_fields


def sync_avis_declaration_manifestations(avis, logger):
    """
    Synchronise un objet AvisManifSportive à partir des données de déclaration-manifestations.

     {
        "id_avis_manif_sportive", "id_dossier_manif_sportive", "etat","service","date_demande",
        "date_reponse","reponse_avis","prescriptions" (chaine vide),"objet_demande",
     }
    """

    # --- Normalisation initiale des dates venant du JSON ---
    for field in ["date_demande", "date_reponse"]:
        if field in avis and avis[field]:
            val = avis[field]

            # Si c’est une chaîne "2025-06-18" ou "2025-06-18T09:00:00"
            if isinstance(val, str):
                try:
                    val = datetime.fromisoformat(val)
                except ValueError:
                    continue  # format non reconnu, on ignore

            # Si c’est un objet date simple (sans heure)
            if isinstance(val, date) and not isinstance(val, datetime):
                val = datetime.combine(val, datetime.min.time())

            # Rendre aware dans le fuseau local si nécessaire
            if timezone.is_naive(val):
                val = timezone.make_aware(val, timezone.get_current_timezone())

            # Remplacer dans le dict
            avis[field] = val


    try:
        
        dossier = DossierManifSportive.objects.filter(
            numero_dossier_declaration_manifestations=avis["id_dossier_manif_sportive"]
        ).first()

        if not dossier:
            logger.error(f"Aucun DossierManifSportive trouvé pour numéro {avis['id_dossier_manif_sportive']}")
            return None

        # logger.info(f"Dossier trouvé : id={dossier.id}, numero={dossier.numero_dossier_declaration_manifestations}")
    
        obj, created = AvisManifSportive.objects.get_or_create(
            id_avis_manif_sportive=int(avis["id_avis_manif_sportive"]),
            
            defaults={
                "id_dossier_manif_sportive_id": dossier.id,
                "etat": avis["etat"],
                "service": avis["service"],
                "date_demande": avis["date_demande"],
                "date_reponse": avis["date_reponse"],
                "reponse_avis": avis["reponse_avis"],
                "objet_demande": avis["objet_demande"]
            }

        )
    except Exception as e:
        logger.error(f"Erreur lors du get_or_create AvisManifSportive : {e}")
        return None

    # Nouvel Avis
    if created:
        logger.info(f"[CREATE] AvisManifSportive numéro {obj.id_avis_manif_sportive} ({obj.id_dossier_manif_sportive.nom_dossier}).")

    # Avis existant
    else:
        try :
            update_data = {}

            for field, new_value in avis.items():
                
                if field == "id_dossier_manif_sportive" :
                    new_value = DossierManifSportive.objects.filter(numero_dossier_declaration_manifestations=avis["id_dossier_manif_sportive"]).first()
                
                # Ignore les prescriptions et id_dossier_manif_sportive vides
                if (field == "prescriptions" and not new_value) or (field == "id_dossier_manif_sportive" and not new_value) :
                    continue

                update_data[field] = new_value if isinstance(new_value, (date, datetime)) else new_value
            
            # --- Conversion UTC avant update_fields ---
            for field in ["date_demande", "date_reponse"]:
                if field in update_data and isinstance(update_data[field], datetime):
                    val = update_data[field]
                    update_data[field] = timezone.localtime(val, ZoneInfo("UTC"))


            updated_fields = update_fields(
                obj,
                update_data,
                date_fields=[k for k, v in avis.items() if isinstance(v, (date, datetime))]
            )

            if updated_fields:
                obj.save()
                logger.info(f"[SAVE] AvisManifSportive {obj.id_avis_manif_sportive} ({obj.id_dossier_manif_sportive.nom_dossier}) mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
            else:
                logger.info(f"[NO CHANGE] AvisManifSportive {obj.id_avis_manif_sportive} inchangé.")
        
        except Exception as e:
            logger.error(f"❌ Erreur lors de la mise à jour de l’AvisManifSportive existant (ID={obj.id_avis_manif_sportive}), Dossier={obj.id_dossier_manif_sportive_id}): {e}")
            return None
        

    return obj.id

