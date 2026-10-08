"""Configuration, prévisualisation et recalcul des noms DN du Back Office."""

import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import CharField, Prefetch
from django.db.models.functions import Cast
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_POST

from autorisations.models.models_instruction import (
    Champ, Demarche, DemarcheNomDossierElement, DemarcheNomDossierRegle, Dossier, DossierChamp,
    DossierManifestationLiaison,
)
from autorisations.models.models_utilisateurs import DossierBeneficiaire, DossierInterlocuteur
from synchronisation.utils.nom_dossier import (
    ATTRIBUTS_NOM_DOSSIER, TRANSFORMATIONS_NOM_DOSSIER, compiler_regles_nommage,
    champs_dm_nommage_autorises, construire_contexte_nommage, generer_nom_dossier,
    cle_correspondance_nommage,
)


def champ_nommage_autorise(champ):
    return bool(champ.id_ds) and champ.id_champ_type.type not in {
        "repetition", "piece_justificative", "carte", "explication", "header",
    }


def demarche_est_manifestation_sportive(demarche):
    return (getattr(demarche, "type", None) or "").casefold() == "manifestations sportives"


def valider_transformation_personnalisee(configuration):
    if not isinstance(configuration, dict):
        raise ValidationError("La transformation personnalisée est invalide.")
    correspondances = configuration.get("correspondances")
    comportement = configuration.get("sans_correspondance", "conserver")
    if comportement not in ("conserver", "ignorer_regle"):
        raise ValidationError("Le comportement sans correspondance est invalide.")
    if not isinstance(correspondances, list) or not 1 <= len(correspondances) <= 100:
        raise ValidationError("Ajoutez entre 1 et 100 correspondances à la transformation personnalisée.")
    resultat, valeurs = [], set()
    for correspondance in correspondances:
        if not isinstance(correspondance, dict):
            raise ValidationError("Une correspondance personnalisée est invalide.")
        valeur, texte = correspondance.get("valeur"), correspondance.get("texte")
        if not isinstance(valeur, str) or not valeur.strip() or len(valeur) > 1000:
            raise ValidationError("La valeur à remplacer est vide ou trop longue (1 000 caractères maximum).")
        if not isinstance(texte, str) or len(texte) > 1000:
            raise ValidationError("Le texte de remplacement est invalide (1 000 caractères maximum).")
        cle = cle_correspondance_nommage(valeur)
        if cle in valeurs:
            raise ValidationError(f"La valeur « {valeur.strip()} » est définie plusieurs fois dans une transformation.")
        valeurs.add(cle)
        resultat.append({"valeur": valeur.strip(), "texte": texte.strip()})
    return {"correspondances": resultat, "sans_correspondance": comportement}


def valider_regles_nommage(payload, demarche):
    regles = payload.get("regles")
    if not isinstance(regles, list) or len(regles) > 50:
        raise ValidationError("La liste de règles est invalide (50 règles maximum).")
    champs = {
        champ.pk: champ for champ in Champ.objects.filter(id_demarche=demarche)
        .select_related("id_champ_type") if champ_nommage_autorise(champ)
    }
    champs_dm = {
        champ.name: champ for champ in champs_dm_nommage_autorises()
    } if demarche_est_manifestation_sportive(demarche) else {}
    resultat = []
    for ordre, regle in enumerate(regles, 1):
        if not isinstance(regle, dict):
            raise ValidationError("Une règle est invalide.")
        libelle = regle.get("libelle", "")
        elements = regle.get("elements")
        actif = regle.get("actif", True)
        if not isinstance(libelle, str) or len(libelle) > 150 or not isinstance(actif, bool):
            raise ValidationError(f"Le libellé ou l'activation de la règle {ordre} est invalide.")
        if not isinstance(elements, list) or not 1 <= len(elements) <= 100:
            raise ValidationError(f"La règle {ordre} doit contenir entre 1 et 100 éléments.")
        normalises = []
        for element in elements:
            if not isinstance(element, dict):
                raise ValidationError(f"Un élément de la règle {ordre} est invalide.")
            type_element = element.get("type")
            transformation = element.get("transformation", "aucune")
            if not isinstance(transformation, str) or transformation not in TRANSFORMATIONS_NOM_DOSSIER:
                raise ValidationError("Une transformation est invalide.")
            configuration = {}
            if transformation == "personnalisee":
                if type_element == "texte":
                    raise ValidationError("Une transformation personnalisée s'applique à une variable, pas à un texte fixe.")
                configuration = valider_transformation_personnalisee(element.get("configuration_transformation"))
            valeur = {"type": type_element, "transformation": transformation, "configuration_transformation": configuration}
            if type_element == "texte":
                texte = element.get("texte")
                if not isinstance(texte, str) or not texte or len(texte) > 1000:
                    raise ValidationError("Un texte fixe est vide ou trop long (1 000 caractères maximum).")
                valeur.update(texte=texte, transformation="aucune", libelle="Texte fixe")
            elif type_element == "champ_dn":
                id_champ = element.get("id_champ")
                if type(id_champ) is not int or id_champ not in champs:
                    raise ValidationError("Un champ sélectionné n'appartient pas à cette démarche ou n'est pas exploitable.")
                champ = champs[id_champ]
                valeur.update(id_champ=champ.pk, id_ds=champ.id_ds, libelle=champ.nom)
            elif type_element == "champ_dm" and element.get("champ_dm") in champs_dm:
                champ_dm = champs_dm[element["champ_dm"]]
                valeur.update(champ_dm=champ_dm.name, libelle=str(champ_dm.verbose_name).capitalize())
            elif (type_element == "attribut" and isinstance(element.get("attribut"), str)
                  and element["attribut"] in ATTRIBUTS_NOM_DOSSIER):
                attribut = element["attribut"]
                valeur.update(attribut=attribut, libelle=ATTRIBUTS_NOM_DOSSIER[attribut])
            else:
                raise ValidationError("Une source de nommage est invalide.")
            normalises.append(valeur)
        if not any(element["type"] != "texte" for element in normalises):
            raise ValidationError(f"La règle {ordre} doit contenir au moins une variable.")
        resultat.append({"libelle": libelle.strip(), "ordre": ordre, "actif": actif, "elements": normalises})
    return resultat


def lire_payload(request):
    try:
        payload = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("Les données envoyées sont invalides.")
    if not isinstance(payload, dict):
        raise ValidationError("Les données envoyées sont invalides.")
    return payload


def dossiers_avec_contexte_nommage(queryset, regles):
    ids_champs_dn = {
        str(element["id_ds"]) for regle in regles for element in regle["elements"]
        if element["type"] == "champ_dn"
    }
    champs_dm = {
        element["champ_dm"] for regle in regles for element in regle["elements"]
        if element["type"] == "champ_dm"
    }
    prefetches = [
        Prefetch("dossierchamp_set", queryset=DossierChamp.objects.filter(
            # Les formulaires DN peuvent avoir été modifiés : un même champ DN
            # (id_ds) peut alors correspondre à plusieurs lignes Champ en BDD.
            # Les dossiers historiques doivent rester exploitables au recalcul.
            id_champ__id_ds__in=ids_champs_dn,
        ).select_related("id_champ").only(
            "id", "id_dossier_id", "valeur", "ordre", "id_champ__id_ds",
        ).order_by("ordre", "id"), to_attr="champs_nommage"),
        Prefetch("dossierinterlocuteur_set", queryset=DossierInterlocuteur.objects
            .select_related("id_demandeur_intermediaire").order_by("id").prefetch_related(
                Prefetch("dossierbeneficiaire_set", queryset=DossierBeneficiaire.objects
                    .select_related("id_beneficiaire").order_by("id"), to_attr="beneficiaires_nommage"),
            ), to_attr="interlocuteurs_nommage"),
    ]
    if champs_dm:
        prefetches.append(Prefetch(
            "dossiermanifestationliaison",
            queryset=DossierManifestationLiaison.objects.select_related("id_dossier_manif").only(
                "id", "id_dossier_id", "id_dossier_manif_id",
                *[f"id_dossier_manif__{champ}" for champ in champs_dm],
            ),
            to_attr="liaison_nommage",
        ))
    return queryset.only(
        "id", "numero", "date_depot", "nom_dossier", "nom_dossier_genere", "nom_dossier_plus_parlant",
    ).prefetch_related(*prefetches)


def contexte_nommage_depuis_bdd(dossier, regles=()):
    interlocuteur = next(iter(dossier.interlocuteurs_nommage), None)
    beneficiaire = None
    if interlocuteur:
        liaison = next(iter(interlocuteur.beneficiaires_nommage), None)
        beneficiaire = liaison.id_beneficiaire if liaison else None

    def contact_dict(contact):
        return {champ: getattr(contact, champ, None) for champ in (
            "prenom", "nom", "raison_sociale", "organisation",
        )} if contact else {}

    liaison = getattr(dossier, "liaison_nommage", None)
    if isinstance(liaison, list):
        liaison = liaison[0] if liaison else None
    dossier_dm = {
        champ: getattr(liaison.id_dossier_manif, champ, None)
        for champ in {element["champ_dm"] for regle in regles
                      for element in regle["elements"] if element["type"] == "champ_dm"}
    } if liaison else {}
    return construire_contexte_nommage(
        {"numero": dossier.numero, "date_depot": dossier.date_depot},
        {"beneficiaire": contact_dict(beneficiaire), "demandeur_intermediaire": contact_dict(
            interlocuteur.id_demandeur_intermediaire if interlocuteur else None,
        )},
        [{"champ": {"id_ds": champ.id_champ.id_ds, "valeur": champ.valeur}} for champ in dossier.champs_nommage],
        dossier_dm=dossier_dm,
    )


@login_required
@require_GET
def autocomplete_numeros_dossiers(request, demarche_id):
    """Retourne quelques numéros DN de la seule démarche du Back Office."""
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    recherche = (request.GET.get("q") or "").strip()
    if not recherche.isdigit():
        return JsonResponse({"numeros": []})
    demarche = get_object_or_404(Demarche, pk=demarche_id)
    numeros = Dossier.objects.filter(id_demarche=demarche).annotate(
        numero_texte=Cast("numero", output_field=CharField()),
    ).filter(numero_texte__startswith=recherche).order_by("numero").values_list("numero", flat=True)[:15]
    return JsonResponse({"numeros": [str(numero) for numero in numeros]})


@login_required
@require_POST
def enregistrer_regles_nom_dossier(request, demarche_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    demarche = get_object_or_404(Demarche, pk=demarche_id)
    try:
        regles = valider_regles_nommage(lire_payload(request), demarche)
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    with transaction.atomic():
        Demarche.objects.select_for_update().get(pk=demarche.pk)
        DemarcheNomDossierRegle.objects.filter(id_demarche=demarche).delete()
        objets = DemarcheNomDossierRegle.objects.bulk_create([
            DemarcheNomDossierRegle(id_demarche=demarche, libelle=regle["libelle"], ordre=regle["ordre"], actif=regle["actif"])
            for regle in regles
        ])
        DemarcheNomDossierElement.objects.bulk_create([
            DemarcheNomDossierElement(
                id_regle=objet, ordre=ordre, type_element=element["type"],
                texte=element.get("texte"), id_champ_id=element.get("id_champ"),
                champ_dm=element.get("champ_dm"),
                attribut=element.get("attribut"), transformation=element["transformation"],
                configuration_transformation=element["configuration_transformation"],
            ) for regle, objet in zip(regles, objets)
            for ordre, element in enumerate(regle["elements"], 1)
        ])
    return JsonResponse({"success": True})


@login_required
@require_POST
def previsualiser_nom_dossier(request, demarche_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    demarche = get_object_or_404(Demarche, pk=demarche_id)
    try:
        payload = lire_payload(request)
        regles = valider_regles_nommage(payload, demarche)
        numero = payload.get("numero")
        if not str(numero or "").isdigit():
            raise ValidationError("Renseignez un numéro de dossier DN.")
    except ValidationError as exc:
        return JsonResponse({"error": " ".join(exc.messages)}, status=400)
    dossier = dossiers_avec_contexte_nommage(Dossier.objects.filter(id_demarche=demarche, numero=int(numero)), regles).first()
    if not dossier:
        return JsonResponse({"error": "Ce dossier est introuvable dans cette démarche."}, status=404)
    resultat = generer_nom_dossier(regles, contexte_nommage_depuis_bdd(dossier, regles), expliquer=True)
    resultat.update(
        nom_standard=dossier.nom_dossier, nom_manuel=dossier.nom_dossier_plus_parlant,
        nom_affiche=dossier.nom_dossier_plus_parlant or resultat["nom_genere"] or dossier.nom_dossier,
    )
    return JsonResponse(resultat)


@login_required
@require_POST
def recalculer_noms_dossiers(request, demarche_id):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    demarche = get_object_or_404(Demarche, pk=demarche_id)
    regles = compiler_regles_nommage(DemarcheNomDossierRegle.objects.filter(
        id_demarche=demarche,
    ).prefetch_related(Prefetch(
        "elements", queryset=DemarcheNomDossierElement.objects.select_related("id_champ"),
    )))
    dossiers = dossiers_avec_contexte_nommage(Dossier.objects.filter(id_demarche=demarche).order_by("id"), regles)
    total = modifies = noms_prioritaires = 0
    lot = []
    with transaction.atomic():
        for dossier in dossiers.iterator(chunk_size=200):
            total += 1
            noms_prioritaires += bool(dossier.nom_dossier_plus_parlant)
            nom = generer_nom_dossier(regles, contexte_nommage_depuis_bdd(dossier, regles))["nom_genere"]
            if dossier.nom_dossier_genere != nom:
                dossier.nom_dossier_genere = nom
                lot.append(dossier)
                modifies += 1
            if len(lot) >= 200:
                Dossier.objects.bulk_update(lot, ["nom_dossier_genere"], batch_size=200)
                lot.clear()
        if lot:
            Dossier.objects.bulk_update(lot, ["nom_dossier_genere"], batch_size=200)
    return JsonResponse({"total": total, "modifies": modifies, "noms_prioritaires": noms_prioritaires})
