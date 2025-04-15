from synchronisation.src.functions import extraire_nom_et_extension, get_first_id
from autorisations.models.models_documents import DocumentFormat, DocumentNature


def dossier_document_normalize(doss, emplacement_dossier):
    """
    Normalise les données du document résumé PDF associé à un dossier.
    """
    nom_fichier, extension_fichier = extraire_nom_et_extension(doss["pdf"]["filename"])

    dico_pdf = {
        "numero": doss["number"],
        "id_format": get_first_id(DocumentFormat, format=extension_fichier),
        "id_nature": get_first_id(DocumentNature, nature="Résumé dossier"),
        "url_ds": doss["pdf"]["url"],
        "emplacement": emplacement_dossier,
        "description": f"Résumé du dossier {doss['number']}",
        "titre": nom_fichier,
    }

    return dico_pdf
