from autorisations.models.models_instruction import Champ, Demarche, Dossier
from autorisations.models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierInterlocuteur, GroupeinstructeurDemarche
# from ...BDD.pg_functions import *
from dateutil.parser import parse
from functions import *
from django.db import IntegrityError, models
from datetime import datetime, date


import logging
logger = logging.getLogger('ORM_DJANGO')


def synchro_process (dico):
    logger.info("")
    logger.info(" ----------------- ")
    logger.info("")
    sync_demarche(dico["demarche"])
    sync_groupeinstructeurs_demarches(dico["groupeinstructeurs_demarches"])
    sync_champs(dico["champs"])
    sync_dossiers(dico["dossiers"])
    pass




def sync_demarche(demarche_ds):

    """
    Synchronise un objet Demarche à partir des données récupérées sur D-S.
    demarche_ds = {"id_ds", "numero", "titre", "id_etat", "date_creation", "date_derniere_modif", "description"}
    """

    # On récupère ou on crée la démarche
    demarche_obj, created = Demarche.objects.get_or_create(
        id_ds=demarche_ds["id_ds"],
        numero=demarche_ds["numero"],
        defaults={
            "titre": demarche_ds["titre"],
            "id_etat_id": demarche_ds["id_etat"],
            "date_creation": demarche_ds["date_creation"],
            "date_derniere_modif": demarche_ds["date_derniere_modif"],
            "description": demarche_ds.get("description", "")
        }
    )

    if created:
        logger.info(f"[CREATE] Demarche {demarche_obj.numero} - {demarche_obj.titre} créée.")
    else:
        logger.info(f"[GET] Demarche {demarche_obj.numero} - récupérée depuis PG.")
        updated_fields = []

    # Si l'objet existait déjà, on met à jour les champs au besoin
    if not created:

        if demarche_obj.titre != demarche_ds["titre"]:
            demarche_obj.titre = demarche_ds["titre"]
            updated_fields.append("titre")

        if demarche_obj.id_etat_id != demarche_ds["id_etat"]:
            demarche_obj.id_etat_id = demarche_ds["id_etat"]
            updated_fields.append("id_etat")

        if demarche_obj.date_creation != clean_date(demarche_ds["date_creation"]):
            demarche_obj.date_creation = clean_date(demarche_ds["date_creation"])
            updated_fields.append("date_creation")

        if demarche_obj.date_derniere_modif != clean_date(demarche_ds["date_derniere_modif"]):
            demarche_obj.date_derniere_modif = clean_date(demarche_ds["date_derniere_modif"])
            updated_fields.append("date_derniere_modif")

        if updated_fields:
            demarche_obj.save()
            champs = ", ".join(updated_fields)
            logger.info(f"[SAVE] Demarche {demarche_obj.numero} mise à jour. Champs modifiés : {champs}.")
        else:
            logger.info(f"[NO CHANGE] Aucune mise à jour nécessaire pour la Demarche {demarche_obj.numero}.")



def sync_groupeinstructeurs_demarches(gi_demarche_list):

    """
    Synchronise les objets GroupeinstructeurDemarche à partir des données récupérées sur D-S.
    [{"id_demarche", "id_groupeinstructeur", "id_groupeinstructeur_ds",}, ...]
    """

    for gi in gi_demarche_list:
       
        # On tente de retrouver ou créer l’objet
        obj, created = GroupeinstructeurDemarche.objects.get_or_create(
            id_demarche_id=gi["id_demarche"],
            id_groupeinstructeur_id=gi["id_groupeinstructeur"],
            defaults={
                "id_groupeinstructeur_ds": gi.get("id_groupeinstructeur_ds")
            }
        )

        if created:
            logger.info(f"[CREATE] GroupeinstructeurDemarche (Groupeinstructeur {gi['id_groupeinstructeur']} - Démarche {gi['id_demarche']}) créé.")
        else:
            updated_fields = []

            if obj.id_groupeinstructeur_ds != gi.get("id_groupeinstructeur_ds"):
                logger.info(f"[UPDATE] id_groupeinstructeur_ds → PG : '{obj.id_groupeinstructeur_ds}' --- DS : '{gi.get('id_groupeinstructeur_ds')}'")
                obj.id_groupeinstructeur_ds = gi.get("id_groupeinstructeur_ds")
                updated_fields.append("id_groupeinstructeur_ds")

            if updated_fields:
                obj.save()
                champs = ", ".join(updated_fields)
                logger.info(f"[SAVE] GroupeinstructeurDemarche {obj.id} mis à jour. Champs modifiés : {champs}.")
            # else:
            #     logger.info(f"[NO CHANGE] GroupeinstructeurDemarche {obj.id} inchangé.")



def sync_champs(champs_list):

    """
    Synchronise les objets Champs à partir des données récupérées sur D-S.
    [{ "id_ds", "nom", "id_champ_type", "description", "id_demarche", "requis" }]
    """

    for ch in champs_list :
    
        obj, created = Champ.objects.get_or_create(
            id_ds=ch["id_ds"],
            defaults={
                "nom": ch["nom"],
                "id_champ_type_id": ch["id_champ_type"],
                "description": ch["description"],
                "id_demarche_id": ch.get("id_demarche"),
                "requis": ch["requis"],
            }
        )

        nom_champ_sans_apostrophe = obj.nom.replace("'", " ").replace("’", " ")

        if created:
            logger.info(f"[CREATE] Champ '{nom_champ_sans_apostrophe}' (id: {obj.id}) créé.")
        else:
            # logger.info(f"[GET] Champ '{nom_champ_sans_apostrophe}' (id: {obj.id}) récupéré depuis PG.")
            updated_fields = []

            if obj.nom != ch["nom"]:
                obj.nom = ch["nom"]
                updated_fields.append("nom")

            if obj.id_champ_type_id != ch["id_champ_type"]:
                obj.id_champ_type_id = ch["id_champ_type"]
                updated_fields.append("id_champ_type")

            if obj.description != ch["description"]:
                obj.description = ch["description"]
                updated_fields.append("description")

            if obj.id_demarche_id != ch.get("id_demarche"):
                obj.id_demarche_id = ch.get("id_demarche")
                updated_fields.append("id_demarche")

            if obj.requis != ch["requis"]:
                obj.requis = ch["requis"]
                updated_fields.append("requis")

            if updated_fields:
                obj.save()
                champs = ", ".join(updated_fields).replace("'", " ").replace("’", " ")
                logger.info(f"[SAVE] Champ '{nom_champ_sans_apostrophe}' mis à jour. Champs modifiés : {champs}.")
            # else:
                # logger.info(f"[NO CHANGE] Champ '{nom_champ_sans_apostrophe}' inchangé.")



def sync_dossiers(dossiers_list):
    """
    Synchronise les objets suivants à partir des données récupérées sur D-S.
    [
        {
            'dossier': {...},
            'contacts_externes': {...},
            'dossier_interlocuteur': {...},
            'dossier_beneficiaire': {...},
            'dossier_champs': [...],
            'dossier_document': {...},
            'messages': [...],
            'demandes': [...]
        },
        ...
    ]
    """

    for doss in dossiers_list:
        sync_doss(doss['dossier'])
        ids_beneficiaire_intermediaire = sync_contacts_externes(doss['contacts_externes'])
        id_dossier_interlocuteur = sync_dossier_interlocuteur(doss['dossier_interlocuteur'], ids_beneficiaire_intermediaire)
        sync_dossier_beneficiaire(doss['dossier_beneficiaire'], ids_beneficiaire_intermediaire, id_dossier_interlocuteur) #Probleme nom table a réglé
        # sync_dossier_champs(doss['dossier_champs'])
        # sync_dossier_document(doss['dossier_document'])
        # sync_messages(doss['messages'])
        # sync_demandes(doss['demandes'])



def sync_doss(dossier):
    """
    {
        "id_ds": str,
        "id_etat_dossier": int,
        "id_demarche": int,
        "numero": int,
        "id_groupeinstructeur": int,
        "date_depot": datetime,
        "date_fin_instruction": datetime | None,
        "id_dossier_type": int,
        "id_ds_dossier_parent": str | None,
        "note": str,
        "nom_dossier": str,
        "emplacement": str,
        "date_limite_traitement": datetime,
        "geometrie": dict | None
    }
    """

    defaults = foreign_keys_add_suffixe_id(Dossier, dossier)

    obj, created = Dossier.objects.get_or_create(
        id_ds=dossier["id_ds"],
        numero = dossier["numero"],
        defaults = defaults
    )

    if created:
        logger.info(f"[CREATE] Dossier {obj.numero} (id_ds: {obj.id_ds}) créé.")
    else:
        logger.info(f"[GET] Dossier {obj.numero} (id_ds: {obj.id_ds}) récupéré.")
        updated_fields = []

        for field, new_value in dossier.items():
            # Si le champ est une FK, on ajoute le suffixe _id
            if isinstance(getattr(obj.__class__, field).field, models.ForeignKey):
                field += "_id"

            old_value = getattr(obj, field)

            # Normalisation des dates
            if isinstance(old_value, (date, datetime)) and isinstance(new_value, (date, datetime)):
                old_date = clean_date(old_value)
                new_date = clean_date(new_value)

                if old_date != new_date:
                    print('pg :', old_date, ' --- ds :', new_date)
                    setattr(obj, field, new_date)
                    updated_fields.append(field)

            elif old_value != new_value:
                setattr(obj, field, new_value)
                updated_fields.append(field)

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] Dossier {obj.numero} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
        else:
            logger.info(f"[NO CHANGE] Dossier {obj.numero} inchangé.")



def sync_contacts_externes(contacts_externes):
    """
    {
        "beneficiaire": {
            "email": str | None,
            "id_type": int,
            "nom": str,
            "prenom": str
        },
        "demandeur_intermediaire": {
            "email": str,
            "id_type": int,
            "nom": str,
            "prenom": str
        } | {}
    }
    """

    result_ids = {
        "beneficiaire": None,
        "demandeur_intermediaire": None
    }

    for role, data in contacts_externes.items():
        if not data:
            continue  # permet d'ignorer les dicts vides

        try:

            # Normalisation des valeurs
            nom = data["nom"].strip().capitalize()
            prenom = data["prenom"].strip().capitalize()
            email = data["email"][0].strip().lower()
            
            obj, created = ContactExterne.objects.get_or_create(
                email = email,
                id_type_id = data["id_type"],  # FK suffixée
                # trouver un moyen de ne pas créer de doublons (majuscules, minuscules)
                defaults={
                    "nom": nom,
                    "prenom": prenom,
                    "email": email
                }
            )

            if created:
                logger.info(f"[CREATE] ContactExterne {role} - {obj.prenom} {obj.nom} (email: {obj.email}) créé.")
            else:
                updated_fields = []

                if obj.nom != nom:
                    obj.nom = nom
                    updated_fields.append("nom")

                if obj.prenom != prenom:
                    obj.prenom = prenom
                    updated_fields.append("prenom")
                
                if updated_fields:
                    obj.save()
                    champs = ", ".join(updated_fields).replace("'", " ").replace("’", " ")
                    logger.info(f"[SAVE] Contact Externe {role} - {obj.prenom} {obj.nom} mis à jour. Champs modifiés : {champs}.")


        except IntegrityError as e:
            obj = ContactExterne.objects.filter(email=data["email"][0]).first()
            if obj:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Fallback trouvé pour {data['email']} (id: {obj.id})")
            else:
                logger.warning(f"[INTEGRITY ERROR] Échec création ContactExterne {role} : {e} → Aucun fallback trouvé pour {data['email']}")


        result_ids[role] = obj.id

    return result_ids


def sync_dossier_interlocuteur(dossier_interlocuteur, ids_beneficiaire_intermediaire):
    """
    {
        "id_interlocuteur_ds": str,
        "id_demandeur_intermediaire": int | None,
        "id_dossier": int
    }
    """
    
    result_ids = {
        "dossier_interlocuteur": None
    }

    obj, created = DossierInterlocuteur.objects.get_or_create(
        id_interlocuteur_ds=dossier_interlocuteur["id_interlocuteur_ds"],
        id_dossier_id=dossier_interlocuteur["id_dossier"],
        defaults={
            "id_demandeur_intermediaire_id": ids_beneficiaire_intermediaire["demandeur_intermediaire"]
        }
    )

    if created:
        logger.info(f"[CREATE] DossierInterlocuteur (id_dossier: {obj.id_dossier_id}) créé.")
    else:
        updated_fields = []

        if obj.id_demandeur_intermediaire_id != ids_beneficiaire_intermediaire["demandeur_intermediaire"]:
            obj.id_demandeur_intermediaire_id = ids_beneficiaire_intermediaire["demandeur_intermediaire"]
            updated_fields.append("id_demandeur_intermediaire")

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] DossierInterlocuteur {obj.id} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
        # else:
        #     logger.info(f"[NO CHANGE] DossierInterlocuteur {obj.id} inchangé.")
        
    result_ids["dossier_interlocuteur"] = obj.id
    return result_ids
    



def sync_dossier_beneficiaire(dossier_beneficiaire, ids_beneficiaire_intermediaire, id_dossierInterlocuteur):

    # peut etre aucun interet à remonter dossier_beneficiaire ici ?
    """
    {
        "id_dossier_interlocuteur": int,
        "id_beneficiaire": int
    }
    """
    id_beneficiaire = ids_beneficiaire_intermediaire.get("beneficiaire")
    id_doss_interlocuteur = id_dossierInterlocuteur.get("dossier_interlocuteur")

    if not id_beneficiaire or not id_doss_interlocuteur :
        logger.error(f"[ERROR] DossierBeneficiaire ne peut pas être créé (ID du bénéficiare ou ID du Dossier_Interlocuteur non trouvé)")
    else :
        # PROBLEME : il cherche l'ancienne table demande_beneficiaire au lieu de dossier_beneficiaire
        obj, created = DossierBeneficiaire.objects.get_or_create(
            id_dossier_interlocuteur_id=id_doss_interlocuteur,
            id_beneficiaire_id=id_beneficiaire,
        )

        if created:
            logger.info(f"[CREATE] DossierBeneficiaire (interlocuteur: {id_doss_interlocuteur}, bénéficiaire: {id_beneficiaire}) créé.")



def sync_dossier_champs(dossier_champs):
    """
    [
        {
            "champ": {
                "id_dossier": int,
                "id_champ": int,
                "valeur": str,
                "date_saisie": datetime,
                "geometrie": dict | None,
                "id_document": int | None
            },
            "documents": [  # uniquement pour les champs de type pièce justificative
                {
                    "numero": str | None,
                    "id_format": int,
                    "id_nature": int,
                    "url_ds": str,
                    "emplacement": str,
                    "description": str,
                    "titre": str
                }
            ]
        },
        ...
    ]
    """


def sync_dossier_document(dossier_document):
    """
    {
        "resume_pdf": {
            "numero": str,
            "id_format": int,
            "id_nature": int,
            "url_ds": str,
            "emplacement": str,
            "description": str,
            "titre": str
        },
        "dossier_document": {
            "id_dossier": int,
            "id_document": int
        }
    }
    """


def sync_messages(messages):
    """
    [
        {
            "message": {
                "id_ds": str,
                "body": str,
                "date_envoi": str,
                "piece_jointe": bool,
                "email_emetteur": str,
                "id_dossier": int
            },
            "documents": [  # pièces jointes du message
                {
                    "id_format": int,
                    "id_nature": int,
                    "url_ds": str,
                    "emplacement": str,
                    "description": str,
                    "titre": str
                }
            ],
            "message_documents": [
                {
                    "id_message": int,
                    "id_document": int
                }
            ]
        },
        ...
    ]
    """


def sync_demandes(demandes):
    """
    [
        {
            "id_etat_demande": int,
            "id_priorite": int,
            "id_dossier": int,
            "id_demande_type": int,
            "date_depot": str,
            "date_fin_instruction": str
        },
        ...
    ]
    """




def foreign_keys_add_suffixe_id(model_class, data):
    corrected = {}
    for field, value in data.items():
        if hasattr(model_class, field):
            model_field = getattr(model_class, field)
            if hasattr(model_field, 'field') and isinstance(model_field.field, models.ForeignKey):
                corrected[f"{field}_id"] = value
            else:
                corrected[field] = value
        else:
            corrected[field] = value
    return corrected


def clean_date(val):
    if isinstance(val, datetime):
        return val.date()
    elif isinstance(val, str):
        return parse(val).date()
    return val  # si c’est déjà une date, on ne fait rien
