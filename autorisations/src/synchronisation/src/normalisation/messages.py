from datetime import datetime
from synchronisation.src.functions import get_first_id, clean_email, extraire_nom_et_extension
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, Message, MessageDocument


def message_normalize(doss, id_dossier):
    """
    Transforme les données brutes des messages en structure normalisée pour l'enregistrement.
    
    :param doss: Données brutes du dossier
    :param id_dossier: ID du dossier lié au message
    :return: Liste de messages normalisés
    """

    liste_messages = []

    for m in doss["messages"]:

        contient_pj = True if m["attachments"] else False

        dico_message = {
            "id_ds": m["id"],
            "body": m["body"],
            "date_envoi": m["createdAt"],
            "piece_jointe": contient_pj,
            "email_emetteur": clean_email(m["email"]),
            "id_dossier": id_dossier,
        }

        liste_files_message = []
        liste_msg_doc = []

        if contient_pj and not m.get("email", "").endswith("@reunion-parcnational.fr"):
            for file in m["attachments"]:

                nom_fichier, extension_fichier = extraire_nom_et_extension(file["filename"])
                id_format_doc = get_first_id(DocumentFormat, format=extension_fichier)
                id_nature_doc = get_first_id(DocumentNature, nature="Pièce jointe demandeur")
                liste_files_message.append({
                    "id_format": id_format_doc,
                    "id_nature": id_nature_doc,
                    "url_ds": file["url"],
                    "emplacement": f"/emplacement/a_definir/message{m['id']}",
                    "description": f"Pièce jointe dans la messagerie du dossier {doss['number']}",
                    "titre": nom_fichier,
                })

                liste_msg_doc.append({
                    "id_message": get_first_id(Message, id_ds=m["id"], id_dossier=id_dossier),
                    "id_document": get_first_id(Document, id_format=id_format_doc, id_nature=id_nature_doc, url_ds=file["url"]),
                })

        liste_messages.append({
            'message': dico_message,
            'documents': liste_files_message,
            'message_documents': liste_msg_doc
        })

    return liste_messages