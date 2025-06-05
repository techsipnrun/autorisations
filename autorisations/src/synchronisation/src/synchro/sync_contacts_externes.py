from autorisations.models.models_utilisateurs import ContactExterne
from django.db import IntegrityError
from ..utils.model_helpers import update_fields
import logging

logger = logging.getLogger("SYNCHRONISATION")

def sync_contacts_externes(contacts_externes):
    """
    Synchronise les contacts externes (bénéficiaire et demandeur intermédiaire).
    { 'beneficiaire': {"email", "id_type", "nom", "prenom", "siret", "raison_sociale", "organisation", "adresse"},
      'demandeur_intermediaire': {"email", "id_type", "nom", "prenom"},
    }
    """

    result_ids = {
        "beneficiaire": None,
        "demandeur_intermediaire": None
    }

    for role, data in contacts_externes.items():
        if not data:
            continue

        try:
            email = data["email"]
            id_type = data["id_type"]

            defaults = {k: v for k, v in [("nom", data.get("nom")), ("prenom", data.get("prenom")), ("siret", data.get("siret")), 
                                          ("raison_sociale", data.get("raison_sociale")), ("organisation", data.get("organisation")), 
                                          ("adresse", data.get("adresse"))] if v is not None}


            obj = None
            created = None

            if id_type:
                if email : #Le bénéficiaire peut ne pas avoir d'email

                    # 2 Contact Externes ne peuvent pas avoir le même email ET le même type
                    obj, created = ContactExterne.objects.get_or_create(
                        email=email,
                        id_type_id=id_type,
                        defaults=defaults
                    )
                else :
                    obj, created = ContactExterne.objects.get_or_create(
                        id_type_id=id_type,
                        nom=data.get("nom"),
                        prenom=data.get("prenom"),
                    )

            else :
  
                logger.error(f"ERROR ---> La normalisation de contact externe {role} n'est pas bonne (absence du type)")

            if created:
                logger.info(f"[CREATE] ContactExterne {role} - {obj.prenom} {obj.nom} (email: {obj.email}) créé.")

            else:
                
                updated_fields = update_fields(obj, defaults)

                if updated_fields:
                    logger.warning(f"Le contact externe de type {role} et avec le mail {obj.email} existe déjà")
                    obj.save()
                    champs = ", ".join(updated_fields).replace("'", " ").replace("’", " ")
                    logger.info(f"[SAVE] {role} - {obj.prenom} {obj.nom} mis à jour. Champs modifiés : {champs}.")
      

        except IntegrityError as e:
            obj = ContactExterne.objects.filter(email=data["email"]).first()
            if obj:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Fallback trouvé pour {data['email']} (id: {obj.id})")
            else:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Aucun fallback trouvé pour {data['email']}")

        result_ids[role] = obj.id

    return result_ids