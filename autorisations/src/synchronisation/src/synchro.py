from autorisations.models.models_instruction import Champ, Demarche
from autorisations.models.models_utilisateurs import GroupeinstructeurDemarche
# from ...BDD.pg_functions import *
from dateutil.parser import parse
from functions import *

import logging
logger = logging.getLogger('ORM_DJANGO')


def synchro_process (dico):
    logger.info("")
    sync_demarche(dico["demarche"])
    sync_groupeinstructeurs_demarches(dico["groupeinstructeurs_demarches"])
    sync_champs(dico["champs"])
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
            else:
                logger.info(f"[NO CHANGE] GroupeinstructeurDemarche {obj.id} inchangé.")



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
            logger.info(f"[GET] Champ '{nom_champ_sans_apostrophe}' (id: {obj.id}) récupéré depuis PG.")
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
            else:
                logger.info(f"[NO CHANGE] Champ '{nom_champ_sans_apostrophe}' inchangé.")











def clean_date(val):
    return val.date() if hasattr(val, 'date') else parse(val).date()

