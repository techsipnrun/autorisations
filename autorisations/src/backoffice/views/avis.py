import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import DatabaseError, IntegrityError, transaction
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from autorisations.models.models_avis import AvisFormulaireChamp, AvisFormulaireConfiguration, AvisNature, AvisThematique
from autorisations.models.models_instruction import Demarche
from autorisations.models.models_utilisateurs import ContactExterne, Instructeur
from instruction.utils.avis_formulaires import CHOIX_IMPORT, CONTEXTES, STRUCTURELS, charger_configuration, configuration_standard, verifier_configuration
from instruction.utils.avis_utils import categories_thematiques_avis, contact_est_conseil_scientifique, repartition_thematiques_avis


logger = logging.getLogger("ORM_DJANGO")


@login_required
@require_http_methods(["GET", "POST"])
def configurer_formulaire(request, contexte):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    if contexte not in CONTEXTES:
        return JsonResponse({"error": "Formulaire inconnu."}, status=404)
    if request.method == "GET":
        thematiques = list(AvisThematique.objects.all().order_by("thematique"))
        demarches = list(Demarche.objects.all().order_by("type"))
        return JsonResponse({
            "champs": charger_configuration(contexte), "standards": configuration_standard(contexte),
            "structurels": sorted(STRUCTURELS),
            "thematiques_par_demarche": repartition_thematiques_avis(thematiques, demarches),
            "choix": {
                "nature": [{"valeur": str(obj.pk), "libelle": str(obj),
                            "nature_type": {"Consultation en interne": "interne", "Demande à une instance": "instance"}.get(obj.nature, "")}
                           for obj in AvisNature.objects.all().order_by("nature")],
                "thematique": [{"valeur": str(obj.pk), "libelle": str(obj)} for obj in thematiques],
                "demarche": [{"valeur": str(obj.pk), "libelle": str(obj)} for obj in demarches],
                "expert_externe": [{"valeur": str(obj.pk), "libelle": str(obj), "est_cs": contact_est_conseil_scientifique(obj)}
                                   for obj in ContactExterne.objects.filter(id_type__type="Instance").order_by("raison_sociale", "nom")],
                "expert_interne": [{"valeur": str(obj.pk), "libelle": str(obj)} for obj in Instructeur.objects.select_related("id_agent_autorisations").order_by("email")],
                "demandeur_avis": [{"valeur": str(obj.pk), "libelle": str(obj)} for obj in Instructeur.objects.select_related("id_agent_autorisations").order_by("email")],
                **{code: [{"valeur": valeur, "libelle": libelle} for valeur, libelle in choix] for code, choix in CHOIX_IMPORT.items()},
                "destinataire": [{"valeur": "CS", "libelle": "CS"}, {"valeur": "BCS", "libelle": "BCS"}],
                "nature_type": [{"valeur": "interne", "libelle": "Consultation en interne"}, {"valeur": "instance", "libelle": "Demande à une instance"}],
                "expert_cs": [{"valeur": "true", "libelle": "Oui"}, {"valeur": "false", "libelle": "Non"}],
            },
        })
    try:
        if len(request.body) > 250000:
            raise ValidationError("Configuration trop volumineuse.")
        donnees = json.loads(request.body)
        champs = verifier_configuration(contexte, donnees.get("champs"))
        # Les identifiants par défaut doivent désigner une valeur existante.
        modeles = {"nature": AvisNature, "thematique": AvisThematique, "demarche": Demarche,
                   "expert_externe": ContactExterne, "expert_interne": Instructeur, "demandeur_avis": Instructeur}
        for champ in champs:
            for variante in [champ, *champ["regles"]]:
                choix = variante.get("choix_autorises")
                if choix is not None and set(AvisThematique.objects.filter(pk__in=choix).values_list("pk", flat=True)) != {int(v) for v in choix}:
                    raise ValidationError("La liste contient une thématique inexistante.")
                valeur = variante.get("defaut", "")
                if valeur and champ["code"] in modeles:
                    if not valeur.isdecimal() or not modeles[champ["code"]].objects.filter(pk=int(valeur)).exists():
                        raise ValidationError(f"Valeur initiale inconnue pour {champ['libelle']}.")
                if champ["code"] == "destinataire" and valeur and valeur not in {"CS", "BCS"}:
                    raise ValidationError("Le destinataire doit être CS ou BCS.")
        with transaction.atomic():
            configuration, _ = AvisFormulaireConfiguration.objects.get_or_create(code=contexte, defaults={"nom": CONTEXTES[contexte]})
            configuration = AvisFormulaireConfiguration.objects.select_for_update().get(pk=configuration.pk)
            for champ in champs:
                code = champ.pop("code")
                AvisFormulaireChamp.objects.update_or_create(id_configuration=configuration, code=code, defaults=champ)
        return JsonResponse({"success": True})
    except (ValueError, TypeError, AttributeError, ValidationError) as erreur:
        message = " ".join(erreur.messages) if isinstance(erreur, ValidationError) else "Configuration JSON invalide."
        return JsonResponse({"success": False, "error": message}, status=400)
    except DatabaseError as erreur:
        logger.exception("[BO AVIS FORMULAIRES] Échec d'enregistrement du contexte %s", contexte)
        cause = erreur.__cause__
        diagnostic = getattr(cause, "diag", None)
        sqlstate = getattr(cause, "sqlstate", None) or getattr(cause, "pgcode", None)
        if contexte == "existant" and sqlstate == "23514" and getattr(diagnostic, "table_name", None) == "avis_formulaire_configuration":
            message = "La base n’autorise pas encore le formulaire « Ajouter un avis existant ». Appliquez la migration 0043 (script 0043_avis_formulaire_existant.sql), puis réessayez. Vos réglages restent présents à l’écran."
        elif sqlstate == "42703":
            message = "La structure des tables de configuration Avis n’est pas à jour. Vérifiez les migrations 0041 à 0044, puis réessayez. Vos réglages restent présents à l’écran."
        elif sqlstate == "42501":
            message = "Le compte applicatif n’a pas les droits nécessaires pour enregistrer cette configuration. Vos réglages restent présents à l’écran."
        else:
            message = "La base de données a refusé l’enregistrement. Consultez les logs serveur. Vos réglages restent présents à l’écran."
        return JsonResponse({"success": False, "error": message}, status=500)


def categories_catalogue():
    categories = {"Autre": "Toutes les démarches"}
    for demarche in Demarche.objects.all().order_by("type"):
        for categorie in categories_thematiques_avis(demarche) or []:
            if categorie != "Autre":
                categories.setdefault(categorie, categorie)
    for categorie in AvisThematique.objects.exclude(demarche__isnull=True).exclude(demarche="").values_list("demarche", flat=True).distinct():
        categories.setdefault(categorie, categorie)
    return [{"valeur": "", "libelle": "Non rattachée"}, {"valeur": "Autre", "libelle": "Toutes les démarches"},
            *[{"valeur": valeur, "libelle": libelle} for valeur, libelle in sorted(categories.items()) if valeur != "Autre"]]


@login_required
@require_http_methods(["GET", "POST"])
def configurer_thematiques(request):
    if not request.user.is_superuser:
        raise PermissionDenied("Cette page est réservée aux administrateurs.")
    if request.method == "GET":
        return JsonResponse({"thematiques": [{"id": t.pk, "thematique": t.thematique, "demarche": t.demarche or ""}
                                             for t in AvisThematique.objects.all().order_by("thematique")],
                             "categories": categories_catalogue()})
    try:
        if len(request.body) > 10000:
            raise ValidationError("Requête trop volumineuse.")
        donnees = json.loads(request.body)
        libelle, categorie = donnees.get("thematique"), donnees.get("demarche", "")
        identifiant = donnees.get("id")
        if not isinstance(libelle, str) or not libelle.strip() or len(libelle) > 180:
            raise ValidationError("Renseignez un nom de thématique (180 caractères maximum).")
        if not isinstance(categorie, str) or categorie not in {c["valeur"] for c in categories_catalogue()}:
            raise ValidationError("Sélectionnez un rattachement existant.")
        if identifiant is not None and (type(identifiant) is not int or identifiant <= 0):
            raise ValidationError("Identifiant de thématique invalide.")
        with transaction.atomic():
            if identifiant is None:
                thematique = AvisThematique()
            else:
                thematique = AvisThematique.objects.select_for_update().filter(pk=identifiant).first()
                if thematique is None:
                    return JsonResponse({"error": "Thématique introuvable."}, status=404)
            if AvisThematique.objects.filter(thematique__iexact=libelle.strip()).exclude(pk=identifiant).exists():
                raise ValidationError("Une thématique porte déjà ce nom.")
            thematique.thematique = libelle.strip()
            thematique.demarche = categorie or None
            thematique.save()
        return JsonResponse({"success": True, "thematique": {"id": thematique.pk, "thematique": thematique.thematique, "demarche": thematique.demarche or ""}})
    except (ValueError, TypeError, AttributeError, ValidationError, IntegrityError) as erreur:
        message = " ".join(erreur.messages) if isinstance(erreur, ValidationError) else "Enregistrement impossible : vérifiez les données et l’unicité du nom."
        return JsonResponse({"success": False, "error": message}, status=400)
