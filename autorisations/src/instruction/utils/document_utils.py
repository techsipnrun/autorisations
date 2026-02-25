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
    emplacements_documents = [
        dd.id_document.emplacement for dd in docs_du_dossier
    ]

    # Annexes instructeur
    annexes_instructeur = [
        dd.id_document
        for dd in docs_du_dossier
        if dd.id_document.id_nature.nature.lower() == "annexe instructeur"
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

    # Indicateur "délibération CA en cours"
    delibCA = any(
        dd.id_document.id_nature.nature.lower() == "déliberation ca"
        and dd.id_document.id_statut and dd.id_document.id_statut.statut != "Envoyé"
        for dd in docs_du_dossier
    )

    return {
        "emplacements_documents": emplacements_documents,
        "annexes_instructeur": annexes_instructeur,
        "titres_documents_actes": list(documents_actes),
        "doc_a_valider": acte_a_valider,
        "doc_a_relire": acte_a_relire,
        "doc_a_signer": acte_a_signer,
        "doc_a_envoyer": acte_a_envoyer,
        "doc_valide_avant_demande_avis": acte_valide_avant_demande_avis,
        "doc_envoye": acte_envoye,
        "doc_envoye_et_publie": acte_envoye_et_publie,
        "resume_pdf_titre": resume_pdf_titre,
        "projets_rapport_ca": projets_rapport_ca,
        "rapports_ca": rapports_ca,
        "delibCA": delibCA,
    }
