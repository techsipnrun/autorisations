from autorisations.models.models_instruction import Champ, ChampType, Demande, Demarche, Dossier, DossierChamp, Message
from autorisations.models.models_utilisateurs import ContactExterne, DossierBeneficiaire, DossierInterlocuteur, GroupeinstructeurDemarche
# from ...BDD.pg_functions import *
from dateutil.parser import parse
from autorisations.models.models_documents import Document, DossierDocument, MessageDocument
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
        
        updated_fields = update_fields(demarche_obj, {
                            "titre": demarche_ds["titre"],
                            "id_etat_id": demarche_ds["id_etat"],
                            "date_creation": clean_date(demarche_ds["date_creation"]),
                            "date_derniere_modif": clean_date(demarche_ds["date_derniere_modif"]),
                        }, date_fields=["date_creation", "date_derniere_modif"])

        if updated_fields:
            demarche_obj.save()
            champs = ", ".join(updated_fields)
            logger.info(f"[SAVE] Demarche {demarche_obj.numero} mise à jour. Champs modifiés : {champs}.")
        else:
            logger.info(f"[NO CHANGE] Demarche {demarche_obj.numero} inchangée.")



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
            updated_fields = update_fields(obj, {"id_groupeinstructeur_ds": gi.get("id_groupeinstructeur_ds"),})

            if updated_fields:
                obj.save()
                champs = ", ".join(updated_fields)
                logger.info(f"[SAVE] GroupeinstructeurDemarche {obj.id} mis à jour. Champs modifiés : {champs}.")



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
           
            updated_fields = update_fields(obj, {
                "nom": ch["nom"],
                "id_champ_type_id": ch["id_champ_type"],
                "description": ch["description"],
                "id_demarche_id": ch.get("id_demarche"),
                "requis": ch["requis"],
            })


            if updated_fields:
                obj.save()
                champs = ", ".join(updated_fields).replace("'", " ").replace("’", " ")
                logger.info(f"[SAVE] Champ '{nom_champ_sans_apostrophe}' mis à jour. Champs modifiés : {champs}.")


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
        id_dossier = sync_doss(doss['dossier'])
        ids_beneficiaire_intermediaire = sync_contacts_externes(doss['contacts_externes'])
        id_dossier_interlocuteur = sync_dossier_interlocuteur(doss['dossier_interlocuteur'], ids_beneficiaire_intermediaire, id_dossier)
        sync_dossier_beneficiaire(ids_beneficiaire_intermediaire, id_dossier_interlocuteur)
        sync_dossier_champs(doss['dossier_champs'], id_dossier)
        sync_dossier_document(doss['dossier_document'], id_dossier)
        sync_messages(doss['messages'], id_dossier)
        sync_demandes(doss['demandes'], id_dossier)



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
        "id_dossier_parent": str | None,
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
        update_data = {}

        for field, new_value in dossier.items():

            model_field = getattr(obj.__class__, field, None)
            field_name = f"{field}_id" if isinstance(getattr(model_field, 'field', None), models.ForeignKey) else field
            update_data[field_name] = clean_date(new_value) if isinstance(new_value, (date, datetime)) else new_value

        updated_fields = update_fields(obj, update_data, date_fields=[k for k, v in dossier.items() if isinstance(v, (date, datetime))])


        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] Dossier {obj.numero} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
        else:
            logger.info(f"[NO CHANGE] Dossier {obj.numero} inchangé.")

    return obj.id



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
            email = data["email"].strip().lower()
            
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


def sync_dossier_interlocuteur(dossier_interlocuteur, ids_beneficiaire_intermediaire, id_dossier):
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
        id_dossier_id=id_dossier,
        defaults={
            "id_demandeur_intermediaire_id": ids_beneficiaire_intermediaire["demandeur_intermediaire"]
        }
    )

    if created:
        logger.info(f"[CREATE] DossierInterlocuteur (id_dossier: {obj.id_dossier_id}) créé.")

    else:
        updated_fields = update_fields(obj, {
            "id_demandeur_intermediaire_id": ids_beneficiaire_intermediaire["demandeur_intermediaire"],
        })

        if updated_fields:
            obj.save()
            logger.info(f"[SAVE] DossierInterlocuteur {obj.id} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")
  
    result_ids["dossier_interlocuteur"] = obj.id
    return result_ids
    



def sync_dossier_beneficiaire(ids_beneficiaire_intermediaire, id_dossierInterlocuteur):


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
        obj, created = DossierBeneficiaire.objects.get_or_create(
            id_dossier_interlocuteur_id=id_doss_interlocuteur,
            id_beneficiaire_id=id_beneficiaire,
        )

        if created:
            logger.info(f"[CREATE] DossierBeneficiaire (interlocuteur: {id_doss_interlocuteur}, bénéficiaire: {id_beneficiaire}) créé.")



def sync_dossier_champs(dossier_champs, id_dossier):
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
    for ch in dossier_champs:
        dossier_champ = ch["champ"]
        documents = ch.get("documents", [])

        id_champ_type = Champ.objects.filter(id=dossier_champ["id_champ"]).values_list("id_champ_type_id", flat=True).first()
        type_du_champ = ChampType.objects.filter(id=id_champ_type).values_list("type", flat=True).first()
        
        #Si le champ est lié à une pièce justificative
        if (documents) :
            
            for doc in documents:
                document_obj, doc_created = Document.objects.get_or_create(
                    url_ds=doc["url_ds"], id_nature_id=doc["id_nature"],
                    defaults={
                        # "numero": doc.get("numero"),
                        "id_format_id": doc["id_format"],
                        "emplacement": doc["emplacement"],
                        "description": doc["description"],
                        "titre": doc["titre"],
                    }
                )

                if doc_created:
                    logger.info(f"[CREATE] Document ({type_du_champ}) pour Champ {dossier_champ["id_champ"]} du Dossier {id_dossier} créé.")

                id_doc = document_obj.id

                champ_obj, created = DossierChamp.objects.get_or_create(
                    id_dossier_id=id_dossier,
                    id_champ_id=dossier_champ["id_champ"],
                    id_document_id=id_doc,
                    defaults={
                        "valeur": dossier_champ["valeur"],
                        "date_saisie": dossier_champ["date_saisie"],
                        "geometrie": dossier_champ.get("geometrie"),
                    }
                )

                if created:
                    logger.info(f"[CREATE] DossierChamp (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}) créé.")

                else :

                    updated_fields = update_fields(champ_obj, {
                        "valeur": dossier_champ["valeur"],
                        "date_saisie": clean_date(dossier_champ["date_saisie"]),
                        "geometrie": dossier_champ.get("geometrie"),
                    }, date_fields=["date_saisie"])

                    if updated_fields:
                        champ_obj.save()
                        champs = ", ".join(updated_fields)
                        logger.info(f"[SAVE] DossierChamp mis à jour (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}). Champs modifiés : {champs}.")
        
        #Si le champ n'est pas lié à une pièce justificative, un document
        else:

            champ_obj, created = DossierChamp.objects.get_or_create(
                id_dossier_id=id_dossier,
                id_champ_id=dossier_champ["id_champ"],
                defaults={
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": dossier_champ["date_saisie"],
                    "geometrie": dossier_champ.get("geometrie"),
                    # "id_document_id": dossier_champ.get("id_document"),
                }
            )

            if created:
                logger.info(f"[CREATE] DossierChamp (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}) créé.")
            
            else:

                updated_fields = update_fields(champ_obj, {
                    "valeur": dossier_champ["valeur"],
                    "date_saisie": clean_date(dossier_champ["date_saisie"]),
                    "geometrie": dossier_champ.get("geometrie"),
                }, date_fields=["date_saisie"])


                if updated_fields:
                    champ_obj.save()
                    champs = ", ".join(updated_fields)
                    logger.info(f"[SAVE] DossierChamp mis à jour (champ: {dossier_champ['id_champ']}, dossier: {id_dossier}). Champs modifiés : {champs}.")

        

def sync_dossier_document(dossier_document, id_dossier):
    """
    {
        "numero": str,
        "id_format": int,
        "id_nature": int,
        "url_ds": str,
        "emplacement": str,
        "description": str,
        "titre": str
    }
    """

    resume = dossier_document

    if not resume :
        logger.warning(f"[WARNING] Le résumé PDF du Dossier {id_dossier} est non renseigné")
        return

    # Crée ou récupère le Document
    doc_obj, created = Document.objects.get_or_create(
        
        id_nature_id=resume["id_nature"],
        numero=resume["numero"],
        emplacement=resume["emplacement"],
        defaults={
            "id_format_id": resume["id_format"],
            "url_ds": resume["url_ds"],
            "description": resume["description"],
            "titre": resume["titre"],
        }
    )

    if created:
        logger.info(f"[CREATE] Document résumé PDF pour Dossier {id_dossier} créé.")
    else:

        updated_fields = update_fields(doc_obj, {
            "id_format_id": resume["id_format"],
            "url_ds": resume["url_ds"],
            "description": resume["description"],
            "titre": resume["titre"],
        })
 
        if updated_fields:
            doc_obj.save()
            champs = ", ".join(updated_fields)
            logger.info(f"[SAVE] Document résumé PDF mis à jour (Dossier {id_dossier}). Champs modifiés : {champs}.")


    link_obj, created = DossierDocument.objects.get_or_create(
        id_dossier_id=id_dossier,
        id_document_id=doc_obj.id
    )

    if created:
        logger.info(f"[CREATE] Lien DossierDocument créé pour Dossier {id_dossier} et Document {doc_obj.id}.")




def sync_messages(messages, id_dossier):
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

    for entry in messages:
        message_data = entry.get("message")
        docs = entry.get("documents", [])

        # Création ou récupération du message
        msg_obj, created = Message.objects.get_or_create(
            id_ds=message_data["id_ds"],
            id_dossier_id=id_dossier,
            defaults={
                "body": message_data["body"],
                "date_envoi": clean_date(message_data["date_envoi"]),
                "piece_jointe": message_data["piece_jointe"],
                "email_emetteur": message_data["email_emetteur"],
                "lu": False,
            }
        )

        if created:
            logger.info(f"[CREATE] Message {msg_obj.id_ds} pour Dossier {id_dossier} créé.")

        else:
            updated_fields = update_fields(msg_obj, {
                "body": message_data["body"],
                "date_envoi": clean_date(message_data["date_envoi"]),
                "piece_jointe": message_data["piece_jointe"],
                "email_emetteur": message_data["email_emetteur"],
            }, date_fields=["date_envoi"])


            if updated_fields:
                msg_obj.save()
                logger.info(f"[SAVE] Message {msg_obj.id_ds} mis à jour. Champs modifiés : {', '.join(updated_fields)}.")

        # Liens documents
        if message_data["piece_jointe"] :
            for doc in docs:
                doc_obj, doc_created = Document.objects.get_or_create(
                    id_nature_id=doc["id_nature"], emplacement=doc["emplacement"], id_format_id=doc["id_format"],
                    defaults={
                        "url_ds" : doc["url_ds"],
                        "description": doc["description"],
                        "titre": doc["titre"],
                    }
                )

                if doc_created:
                    logger.info(f"[CREATE] Document joint à Message {msg_obj.id_ds} créé.")
                else :
                   
                    updated_fields = update_fields(doc_obj, {
                        "url_ds": doc["url_ds"]
                    })

                    if updated_fields:
                        doc_obj.save()
                        logger.info(f"[SAVE] Document {doc_obj.id} ({doc_obj.id_nature.nature}) mis à jour. Champs modifiés : {', '.join(updated_fields)}.")



                msg_doc_obj, link_created = MessageDocument.objects.get_or_create(
                    id_message_id=msg_obj.id,
                    id_document_id=doc_obj.id
                )

                if link_created:
                    logger.info(f"[CREATE] Lien MessageDocument créé (Message: {msg_obj.id}, Document: {doc_obj.id}).")



def sync_demandes(demandes, id_dossier):
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

    for demande in demandes:

        defaults = {
            "date_depot": clean_date(demande["date_depot"]),
            "date_fin_instruction": clean_date(demande["date_fin_instruction"]),
            "id_etat_demande_id" : demande["id_etat_demande"],
            "id_priorite_id" : demande["id_priorite"],
        }

        obj, created = Demande.objects.get_or_create(
            id_dossier_id=id_dossier,
            id_demande_type_id=demande["id_demande_type"],
            defaults=defaults
        )

        if created:
            logger.info(f"[CREATE] Demande {obj.id} pour Dossier {id_dossier} créée.")

        else:
           
            updated_fields = update_fields(obj, {
                "date_depot": clean_date(demande["date_depot"]),
                "date_fin_instruction": clean_date(demande["date_fin_instruction"]),
                "id_etat_demande_id": demande["id_etat_demande"],
                "id_priorite_id": demande["id_priorite"],
            }, date_fields=["date_depot", "date_fin_instruction"])

            if updated_fields:
                obj.save()
                champs = ", ".join(updated_fields)
                logger.info(f"[SAVE] Demande {obj.id} pour Dossier {id_dossier} mise à jour. Champs modifiés : {champs}.")
            else:
                logger.info(f"[NO CHANGE] Demande {obj.id} pour Dossier {id_dossier} inchangée.")


