import re

from django.shortcuts import render


def dossier_introuvable(request, numero, type_dossier):
    """Affiche une erreur 404 lisible pour un dossier DN ou DM absent."""
    return render(
        request,
        "404.html",
        {
            "dossier_introuvable": True,
            "numero_dossier": numero,
            "type_dossier": type_dossier,
        },
        status=404,
    )


def avis_introuvable(request, avis_id, numero_dossier=None):
    """Affiche une erreur 404 dédiée à une demande d'avis absente."""
    return render(
        request,
        "404.html",
        {
            "avis_introuvable": True,
            "numero_avis": avis_id,
            "numero_dossier": numero_dossier,
        },
        status=404,
    )


def erreur_404(request, exception=None):
    """Page 404 générale, enrichie lorsqu'une URL de dossier est reconnue."""
    chemin = request.path_info
    correspondance_dm = re.fullmatch(
        r"/instruction/declaration_manifestations/(?P<numero>\d+)/?", chemin
    )
    correspondance_dn = re.fullmatch(
        r"/(?:instruction|preinstruction)/(?P<numero>\d+)/?", chemin
    )
    correspondance_avis_expert = re.fullmatch(
        r"/reception_avis/(?P<avis_id>\d+)/?", chemin
    )
    correspondance_avis_dossier = re.fullmatch(
        r"/instruction/(?P<numero>\d+)/consultation/(?P<avis_id>\d+)/?",
        chemin,
    )

    if correspondance_dm:
        return dossier_introuvable(request, correspondance_dm.group("numero"), "DM")
    if correspondance_dn:
        return dossier_introuvable(request, correspondance_dn.group("numero"), "DN")
    if correspondance_avis_expert:
        return avis_introuvable(request, correspondance_avis_expert.group("avis_id"))
    if correspondance_avis_dossier:
        return avis_introuvable(
            request,
            correspondance_avis_dossier.group("avis_id"),
            correspondance_avis_dossier.group("numero"),
        )

    return render(request, "404.html", status=404)
