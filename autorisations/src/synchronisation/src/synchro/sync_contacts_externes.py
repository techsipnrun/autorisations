from autorisations.models.models_utilisateurs import ContactExterne
from django.db import IntegrityError
from ..utils.model_helpers import update_fields
import logging

logger = logging.getLogger("SYNCHRONISATION")

def sync_contacts_externes(contacts_externes):
    """
    Synchronise les contacts externes (bénéficiaire et demandeur intermédiaire).
    { 'beneficiaire': {"email", "id_type", "nom", "prenom", "siret", "raison_sociale", "organisation", "adresse", "telephone"},
      'demandeur_intermediaire': {"email", "id_type", "nom", "prenom", "adresse", "organisation", "siret", "raison_sociale", "telephone"},
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
            email = data.get("email")
            # Normalement on recupère TOUJOURS un email
            if not email :
                logger.error(f"Erreur lors de la synchronisation du contact externe ({role}) ---> Aucun email n'a été récupéré sur Démarche Numérique")
                return None

            id_type = data["id_type"]
            siret = data.get("siret")

            defaults = {k: v for k, v in [("nom", data.get("nom")), ("prenom", data.get("prenom")),
                                          ("raison_sociale", data.get("raison_sociale")), ("organisation", data.get("organisation")), 
                                          ("adresse", data.get("adresse")), ("telephone", data.get("telephone"))] if v is not None and str(v).strip() != ''}

            # logger.info(defaults)
            obj = None
            created = None

            if id_type:

                # Clé unique sur id_type, email et siret 
                obj, created = ContactExterne.objects.get_or_create(
                    email=email,
                    id_type_id=id_type,
                    siret=siret or None,
                    defaults=defaults
                )

                # else :
                #     obj, created = ContactExterne.objects.get_or_create(
                #         id_type_id=id_type,
                #         nom=data.get("nom"),
                #         prenom=data.get("prenom"),
                #     )

            else :
                logger.error(f"Erreur lors de la synchronisation du contact externe ---> La normalisation du contact externe {role} n'est pas bonne (absence du type)")
                return None

            if created:
                logger.info(f"[CREATE] ContactExterne {role} - {obj} (email: {obj.email}) créé.")

            else:
                
                updated_fields = update_fields(obj, defaults)

                if updated_fields:
                    logger.warning(f"Le contact externe de type {role} et avec le mail {obj.email} existe déjà")
                    obj.save()
                    champs = ", ".join(updated_fields).replace("'", " ").replace("’", " ")
                    logger.info(f"[SAVE] {role} - {obj} mis à jour. Champs modifiés : {champs}.")
      

        except IntegrityError as e:
            obj = ContactExterne.objects.filter(email=data["email"]).first()
            if obj:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Fallback trouvé pour {data['email']} (id: {obj.id})")
            else:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Aucun fallback trouvé pour {data['email']}")

        result_ids[role] = obj.id

    return result_ids