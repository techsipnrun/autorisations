import logging
from urllib.parse import parse_qs, unquote, urlparse
from synchronisation.src.utils.conversion import clean_email, extraire_nom_et_extension, parse_datetime_with_tz
from synchronisation.src.utils.model_helpers import get_first_id
from autorisations.models.models_documents import DocumentFormat, DocumentNature, Message, MessageDocument

logger = logging.getLogger('ORM_DJANGO')

def message_normalize(doss, emplacement_dossier):
    """
    Transforme les données brutes des messages en structure normalisée pour l'enregistrement.
    
    :param doss: Données brutes du dossier
    :return: Liste de messages normalisés
    """

    liste_messages = []

    email_usager = clean_email(doss.get("usager", {}).get("email", ""))
    email_demandeur = clean_email(doss.get("demandeur", {}).get("email", ""))

    for m in doss["messages"]:
        contient_pj = True if m["attachments"] else False

        #On recupère seulement les messages non vides
        if m["body"] or contient_pj:
            emetteur = clean_email(m.get("email", ""))

            dico_message = {
                "id_ds": m["id"],
                "body": m["body"],
                "date_envoi": parse_datetime_with_tz(m["createdAt"]),
                "piece_jointe": contient_pj,
                "email_emetteur": clean_email(m["email"]),
            }

            liste_files_message = []
            # liste_msg_doc = []
            # if contient_pj and not m.get("email", "").endswith("@reunion-parcnational.fr"):

            # Si le message provient du demandeur (bénéficiaire ou demandeur intermédiaire)
            if contient_pj :
                if emetteur in [email_usager, email_demandeur]:
                    for file in m["attachments"]:

                        nom_fichier, extension_fichier = extraire_nom_et_extension(file["filename"])

                        id_format_doc = get_first_id(DocumentFormat, format=extension_fichier)
                        if not id_format_doc:
                            logger.error(f"[PJ Message] Format de document inconnu : {extension_fichier} pour le dossier {doss["number"]}")
                            continue

                        id_nature_doc = get_first_id(DocumentNature, nature="Pièce jointe message")
                        liste_files_message.append({
                            "id_format": id_format_doc,
                            "id_nature": id_nature_doc,
                            "url_ds": file["url"],
                            "emplacement": f"{emplacement_dossier}/Annexes/",
                            "description": f"Pièce jointe dans la messagerie du dossier {doss['number']}",
                            "titre": f"{nom_fichier}.{extension_fichier}",
                        })

                # Si le message provient de l'instructeur
                else:
                    # Ici c'est pour le cas ou on joint un fichier (autre qu'un acte ou un avisCS) depuis DS. 
                    # Attention pour le moment ca ne fait pas de différence entre une PJ annexe et un acte ou un avis CS
                    for file in m["attachments"]:
                        
                        query = urlparse(file["url"]).query
                        params = parse_qs(query)
                        filename = unquote(params.get("filename", [""])[0])
                        nom_fichier, extension_fichier = extraire_nom_et_extension(filename)

                        id_format_doc = get_first_id(DocumentFormat, format=extension_fichier)
                        if not id_format_doc:
                            logger.error(f"[PJ Message] Format de document inconnu : {extension_fichier} pour le dossier {doss["number"]}")
                            continue

                        id_nature_doc = get_first_id(DocumentNature, nature="Annexe instructeur")
                        liste_files_message.append({
                            "id_format": id_format_doc,
                            "id_nature": id_nature_doc,
                            "url_ds": file["url"],
                            "emplacement": f"{emplacement_dossier}/Annexes/",
                            "description": f"Annexe instructeur envoyée dans la messagerie du dossier {doss['number']}",
                            "titre": f"{nom_fichier}.{extension_fichier}",
                        })


            liste_messages.append({
                'message': dico_message,
                'documents': liste_files_message
                # 'message_documents': liste_msg_doc
            })

    return liste_messages