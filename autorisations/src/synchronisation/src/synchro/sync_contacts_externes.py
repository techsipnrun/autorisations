from autorisations.models.models_utilisateurs import ContactExterne
from django.db import IntegrityError
from functions import update_fields
import logging

logger = logging.getLogger("ORM_DJANGO")

def sync_contacts_externes(contacts_externes):
    """
    Synchronise les contacts externes (bénéficiaire et demandeur intermédiaire).
    { 'beneficiaire': {"email", "id_type", "nom", "prenom"},
      'demandeur_intermediaire': {"email", "id_type", "nom", "prenom"} }
    """

    result_ids = {
        "beneficiaire": None,
        "demandeur_intermediaire": None
    }

    for role, data in contacts_externes.items():
        if not data:
            continue

        try:
            nom = data["nom"]
            prenom = data["prenom"]
            email = data["email"]
            if email :
                obj, created = ContactExterne.objects.get_or_create(
                    email=email,
                    id_type_id=data["id_type"],
                    defaults={
                        "nom": nom,
                        "prenom": prenom,
                        "email": email
                    }
                )
            else :
                obj, created = ContactExterne.objects.get_or_create(
                    id_type_id=data["id_type"],
                    nom=nom,
                    prenom=prenom,
                    defaults={
                        "email": email
                    }
                )

            if created:
                logger.info(f"[CREATE] ContactExterne {role} - {obj.prenom} {obj.nom} (email: {obj.email}) créé.")
            else:
                updated_fields = update_fields(obj, {
                    "nom": nom,
                    "prenom": prenom,
                })

                if updated_fields:
                    obj.save()
                    champs = ", ".join(updated_fields).replace("'", " ").replace("’", " ")
                    logger.info(f"[SAVE] Contact Externe {role} - {obj.prenom} {obj.nom} mis à jour. Champs modifiés : {champs}.")

        except IntegrityError as e:
            obj = ContactExterne.objects.filter(email=data["email"]).first()
            if obj:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Fallback trouvé pour {data['email']} (id: {obj.id})")
            else:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Aucun fallback trouvé pour {data['email']}")

        result_ids[role] = obj.id

    return result_ids