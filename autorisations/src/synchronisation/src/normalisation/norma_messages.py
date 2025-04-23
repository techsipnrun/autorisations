from synchronisation.src.functions import get_first_id, clean_email, extraire_nom_et_extension, parse_datetime_with_tz
from autorisations.models.models_documents import Document, DocumentFormat, DocumentNature, Message, MessageDocument


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
        if contient_pj and emetteur in [email_usager, email_demandeur]:
            for file in m["attachments"]:

                nom_fichier, extension_fichier = extraire_nom_et_extension(file["filename"])
                id_format_doc = get_first_id(DocumentFormat, format=extension_fichier)
                id_nature_doc = get_first_id(DocumentNature, nature="Pièce jointe demandeur")
                liste_files_message.append({
                    "id_format": id_format_doc,
                    "id_nature": id_nature_doc,
                    "url_ds": file["url"],
                    "emplacement": f"{emplacement_dossier}/Annexes/",
                    "description": f"Pièce jointe dans la messagerie du dossier {doss['number']}",
                    "titre": f"{nom_fichier}.{extension_fichier}",
                })

                # liste_msg_doc.append({
                #     "id_message": get_first_id(Message, id_ds=m["id"], id_dossier=id_dossier),
                #     "id_document": get_first_id(Document, id_format=id_format_doc, id_nature=id_nature_doc, url_ds=file["url"]),
                # })

        liste_messages.append({
            'message': dico_message,
            'documents': liste_files_message
            # 'message_documents': liste_msg_doc
        })

    return liste_messages