import os

import smbclient

from autorisations.models.models_documents import Document, DossierDocument


NATURES_VALIDES = ['Déliberation CA', 'Arrêté directeur', 'Avis simple', 'Avis conforme']
NATURES_VALIDES_AVEC_RAPPORT = NATURES_VALIDES + ["Projet Rapport CA"]


def build_documents_for_dossier(dossier):
    """
    Construit toutes les informations liées aux documents / actes d’un dossier.
    Retourne un dict directement utilisable dans le template.
    """

    # Tous les documents liés au dossier
    docs_du_dossier = (
        DossierDocument.objects
        .filter(id_dossier=dossier)
        .select_related(
            "id_document__id_statut",
            "id_document__id_nature"
        )
    )

    # Liste brute des emplacements
    emplacements_documents = [ f"{dd.id_document.emplacement}{dd.id_document.titre}" for dd in docs_du_dossier ]

    # Annexes instructeur
    justificatifs_classement_tous = [
        dd.id_document
        for dd in docs_du_dossier
        if (dd.id_document.description or "").startswith("Justificatif du classement sans suite")
    ]
    justificatifs_classement = sorted(
        justificatifs_classement_tous,
        key=lambda document: document.date,
        reverse=True,
    )[:1]

    annexes_instructeur = [
        dd.id_document
        for dd in docs_du_dossier
        if dd.id_document.id_nature.nature.lower() == "annexe instructeur"
        and dd.id_document not in justificatifs_classement_tous
    ]

    # Liste des titres pour la section Actes du NAS
    documents_actes = Document.objects.filter(
        emplacement=f"{dossier.emplacement}/Actes/"
    ).values_list("titre", flat=True)

    # Actes filtrés par statut & nature
    def filtre_actes(statuts, natures=None, published_only=False):
        résultats = []
        for dd in docs_du_dossier:
            doc = dd.id_document
            stat = doc.id_statut.statut.lower() if doc.id_statut else ""
            nat = doc.id_nature.nature if doc.id_nature else ""

            if stat in statuts and (natures is None or nat in natures):
                if not published_only or doc.publie_au_raa:
                    résultats.append(doc)

        return résultats

    acte_a_valider = filtre_actes(["à valider"], NATURES_VALIDES)
    acte_a_relire = filtre_actes(["à relire"], NATURES_VALIDES_AVEC_RAPPORT)
    acte_a_signer = filtre_actes(["à signer"], NATURES_VALIDES)
    acte_a_envoyer = filtre_actes(["à envoyer"], NATURES_VALIDES)
    acte_valide_avant_demande_avis = filtre_actes(["validé avant demande d'avis"], NATURES_VALIDES)
    acte_envoye = filtre_actes(["envoyé"], NATURES_VALIDES)
    acte_envoye_et_publie = filtre_actes(["envoyé"], NATURES_VALIDES, published_only=True)
    acte_envoye_et_pas_publie = [doc for doc in acte_envoye if not doc.publie_au_raa]

    # Paramètres PDF
    resume_pdf_titre = f"dossier-{dossier.numero}.pdf"

    # Rapports CA
    projets_rapport_ca = [
        dd.id_document
        for dd in docs_du_dossier
        if dd.id_document.id_nature.nature.lower() == "projet rapport ca"
    ]

    rapports_ca = [
        dd.id_document
        for dd in docs_du_dossier
        if dd.id_document.id_nature.nature.lower() == "rapport ca"
    ]

    rapports_ca_envoyes = [
        dd.id_document
        for dd in docs_du_dossier
        if dd.id_document.id_nature.nature.lower() == "rapport ca"
        and dd.id_document.id_statut
        and dd.id_document.id_statut.statut.lower() == "envoyé"
    ]

    # Indicateur "délibération CA en cours"
    delibCA = any(
        dd.id_document.id_nature.nature.lower() == "déliberation ca"
        and dd.id_document.id_statut and dd.id_document.id_statut.statut.lower() != "envoyé"
        for dd in docs_du_dossier
    )

    delibCA_envoye_ou_non = any(
        dd.id_document.id_nature.nature.lower() == "déliberation ca"
        and dd.id_document.id_statut
        for dd in docs_du_dossier
    )



    work_files = []

    dossier_work_path = os.path.join(os.environ.get("NAS_ROOT"), dossier.emplacement, "Work")
    dossier_work_path = dossier_work_path.replace("\\", "/")

    if smbclient.path.exists(dossier_work_path):
        for nom in smbclient.listdir(dossier_work_path):
            lower = nom.lower()
            if lower.endswith((".doc", ".docx", ".odt")):
                work_files.append(nom)

    work_files.sort(key=str.lower)



    return {
        "emplacements_documents": emplacements_documents,
        "annexes_instructeur": annexes_instructeur,
        "justificatifs_classement": justificatifs_classement,
        "titres_documents_actes": list(documents_actes),
        "doc_a_valider": acte_a_valider,
        "doc_a_relire": acte_a_relire,
        "doc_a_signer": acte_a_signer,
        "doc_a_envoyer": acte_a_envoyer,
        "doc_valide_avant_demande_avis": acte_valide_avant_demande_avis,
        "doc_envoye": acte_envoye,
        "doc_envoye_et_publie": acte_envoye_et_publie,
        "acte_envoye_et_pas_publie": acte_envoye_et_pas_publie,
        "resume_pdf_titre": resume_pdf_titre,
        "projets_rapport_ca": projets_rapport_ca,
        "rapports_ca": rapports_ca,
        "rapports_ca_envoyes": rapports_ca_envoyes,
        "delibCA": delibCA,
        "delibCA_envoye_ou_non": delibCA_envoye_ou_non,
        "work_files": work_files,
    }



def normaliser_emplacement(emplacement: str | None) -> str:
    if not emplacement:
        return "/"

    emplacement = emplacement.strip().replace("\\", "/")

    while "//" in emplacement:
        emplacement = emplacement.replace("//", "/")

    if not emplacement.endswith("/"):
        emplacement += "/"

    return emplacement
