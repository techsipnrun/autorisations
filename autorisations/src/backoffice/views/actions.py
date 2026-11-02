"""Administration des ensembles d'ActionsPossibles, sans exécuter d'action."""
from functools import wraps
import hashlib
import json
import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.db import DatabaseError, IntegrityError, connection, transaction
from django.db.models import CharField
from django.db.models.functions import Cast
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods

from autorisations.models.models_instruction import (
    ActionsPossibles, ActionsPriorites, ChangementEtape, Demarche, Dossier,
    DossierManifSportive, DossierManifestationLiaison, EtapeDossier,
)
from autorisations.models.models_utilisateurs import Groupeinstructeur
from instruction.utils.actions_possibles import (
    CRITERES, PROFILS, charger_ordres, contexte_dm, contexte_dossier,
    evaluer_actions, filtres_niveau, niveau_regle, scope_regle, verifier_ordre,
)
from instruction.utils.actions_interface import (
    CIRCUITS, charger_actions, disponibilite, fragment_action, interface_etape,
)

logger = logging.getLogger("ORM_DJANGO")
SCOPE = ("id_etape_id", "present_sur_dn", *CRITERES)


def api(methodes):
    def decorer(fonction):
        @login_required
        @require_http_methods(methodes)
        @wraps(fonction)
        def vue(request, *args, **kwargs):
            if not request.user.is_superuser:
                raise PermissionDenied("Cette page est réservée aux administrateurs.")
            try:
                return fonction(request, *args, **kwargs)
            except (ValueError, TypeError, KeyError) as exc:
                return JsonResponse({"success": False, "error": str(exc) or "Données invalides."}, status=400)
            except ObjectDoesNotExist:
                return JsonResponse({"success": False, "error": "Une donnée sélectionnée n’existe plus. Rechargez la page."}, status=400)
            except DatabaseError:
                logger.exception("Échec du paramétrage des actions possibles")
                return JsonResponse({"success": False, "error": "Impossible d’enregistrer ou de lire la configuration. Vérifiez l’installation SQL et les droits du compte applicatif."}, status=503)
        return vue
    return decorer


def lire_json(request):
    if len(request.body) > 131072:
        raise ValueError("La configuration envoyée est trop volumineuse.")
    try:
        donnees = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValueError("Le contenu envoyé n’est pas un JSON valide.")
    if not isinstance(donnees, dict):
        raise ValueError("Une configuration objet est attendue.")
    return donnees


def circuit_valide(code):
    if code not in PROFILS:
        raise ValueError("Circuit inconnu.")
    return code


def identifiant(valeur):
    if type(valeur) is not int or valeur <= 0:
        raise ValueError("Identifiant invalide.")
    return valeur


def verifier_scope(scope):
    if not isinstance(scope, dict) or set(scope) != set(SCOPE):
        raise ValueError("Les critères de la configuration sont incomplets.")
    if type(scope["present_sur_dn"]) is not bool or scope["coeur_de_parc"] not in (None, True, False):
        raise ValueError("Présence DN ou cœur de parc invalide.")
    if scope["coeur_de_parc"] is not None and type(scope["coeur_de_parc"]) is not bool:
        raise ValueError("Cœur de parc invalide.")
    for cle, modele in (("id_etape_id", EtapeDossier), ("id_demarche_id", Demarche), ("id_groupe_instructeur_id", Groupeinstructeur)):
        valeur = scope[cle]
        if valeur is None and cle != "id_etape_id":
            continue
        if not modele.objects.filter(pk=identifiant(valeur)).exists():
            raise ValueError("Une étape, démarche ou un groupe sélectionné n’existe plus.")
    if scope["type_manif_sportive"] not in (None, "Dossier DN", "Dossier DM", "Dossier complet"):
        raise ValueError("Type de dossier sportif invalide.")
    return dict(scope)


def verifier_contexte(circuit, contexte):
    if circuit == "dn":
        if contexte["type_manif_sportive"] is not None or contexte["coeur_de_parc"] is not None:
            raise ValueError("Les critères sportifs sont réservés aux manifestations sportives.")
        if contexte["id_demarche_id"] and Demarche.objects.get(pk=contexte["id_demarche_id"]).type == "Manifestations sportives":
            raise ValueError("Utilisez le circuit manifestations sportives pour cette démarche.")
    else:
        if contexte["id_demarche_id"] and Demarche.objects.get(pk=contexte["id_demarche_id"]).type != "Manifestations sportives":
            raise ValueError("Ce circuit est réservé à la démarche manifestations sportives.")
        if circuit == "dm" and (contexte["present_sur_dn"] or contexte["id_groupe_instructeur_id"] is not None or contexte["type_manif_sportive"] not in (None, "Dossier DM")):
            raise ValueError("Un DM seul est absent de DN, sans critère de groupe et de type DM.")
        if circuit == "sportif" and contexte["type_manif_sportive"] not in (None, "Dossier DN", "Dossier complet"):
            raise ValueError("Choisissez DN seul ou DN lié à DM.")
        if circuit == "sportif" and contexte["type_manif_sportive"] == "Dossier DN" and contexte["coeur_de_parc"] is not None:
            raise ValueError("Le cœur de parc est connu ici uniquement via un dossier DM lié.")


def signature(regles):
    valeurs = sorted((regle.pk, regle.id_changement_etape_id) for regle in regles)
    return hashlib.sha256(json.dumps(valeurs).encode()).hexdigest()


def verrouiller(etapes):
    # Verrou transactionnel, sans écriture ni droit UPDATE sur le référentiel
    # des étapes. Une même étape est verrouillée quel que soit le circuit.
    if connection.vendor == "postgresql":
        with connection.cursor() as curseur:
            for etape in sorted(set(etapes)):
                curseur.execute("SELECT pg_advisory_xact_lock(%s, %s)", [0x41474944, etape])


def dans_circuit(circuit, scope, demarches):
    demarche = demarches.get(scope["id_demarche_id"])
    sportif = demarche and demarche.type == "Manifestations sportives"
    if circuit == "dn":
        return not sportif and scope["type_manif_sportive"] is None and scope["coeur_de_parc"] is None
    if demarche and not sportif:
        return False
    if circuit == "dm":
        # Une règle entièrement générale, sans type, appartient aux parcours DN.
        if all(scope[cle] is None for cle in CRITERES):
            return False
        return not scope["present_sur_dn"] and scope["id_groupe_instructeur_id"] is None and scope["type_manif_sportive"] in (None, "Dossier DM")
    return scope["type_manif_sportive"] in (None, "Dossier DN", "Dossier complet")


def etapes_disponibles(action, etapes):
    fragments = {interface: fragment_action(action, interface) for interface in ("preinstruction", "instruction", "dm")}
    return {circuit: [etape.pk for etape in etapes if fragments[interface_etape(circuit, etape.etape)][0]] for circuit in CIRCUITS}


def serialiser_action(action, etapes):
    return {"id": action.pk, "nom": action.action, "code": action.code,
            "disponibles": etapes_disponibles(action, etapes)}


@api(["GET"])
def catalogue(request):
    ordres, installe = charger_ordres()
    demarches = list(Demarche.objects.all().order_by("type"))
    groupes = list(Groupeinstructeur.objects.all().order_by("nom"))
    actions = charger_actions()
    etapes = list(EtapeDossier.objects.all().order_by("etape"))
    regles = ActionsPossibles.objects.select_related("id_changement_etape").all()
    ensembles = {}
    etapes_dm = set()
    for regle in regles:
        if regle.type_manif_sportive == "Dossier DM" and not regle.present_sur_dn:
            etapes_dm.add(regle.id_etape_id)
        scope = scope_regle(regle)
        cle = json.dumps(scope, sort_keys=True)
        ensembles.setdefault(cle, {"scope": scope, "regles": []})["regles"].append(regle)
    demarches_par_id = {demarche.pk: demarche for demarche in demarches}
    configurations = []
    for ensemble in ensembles.values():
        scope, lignes = ensemble["scope"], ensemble["regles"]
        niveaux = {circuit: niveau_regle(circuit, scope) for circuit in PROFILS if dans_circuit(circuit, scope, demarches_par_id)}
        configurations.append({"scope": scope, "ids": sorted(ligne.pk for ligne in lignes),
                               "actions": sorted({ligne.id_changement_etape_id for ligne in lignes}),
                               "signature": signature(lignes), "niveaux": niveaux})
    return JsonResponse({"success": True, "priorites_installees": installe, "ordres": ordres,
                         "profils": {code: {"nom": profil["nom"], "niveaux": [
                             {"code": cle, "nom": nom, "champs": list(champs)} for cle, nom, champs in profil["niveaux"]]}
                                     for code, profil in PROFILS.items()},
                         "etapes": [{"id": objet.pk, "nom": objet.etape,
                                     "est_archivage": objet.est_archivage,
                                     "disponible_dm": objet.est_archivage or objet.pk in etapes_dm}
                                    for objet in etapes],
                         "demarches": [{"id": objet.pk, "nom": objet.type or str(objet.pk), "sportif": objet.type == "Manifestations sportives"} for objet in demarches],
                         "groupes": [{"id": objet.pk, "nom": objet.nom} for objet in groupes],
                         "actions": [serialiser_action(objet, etapes) for objet in actions],
                         "configurations": configurations})


@api(["POST"])
def enregistrer_priorites(request):
    donnees = lire_json(request)
    circuit = circuit_valide(donnees["circuit"])
    ordre = verifier_ordre(circuit, donnees["ordre"])
    with transaction.atomic():
        # Verrou commun même si la ligne de ce circuit n'existe pas encore.
        verrouiller([0])
        actuel = charger_ordres()
        if not actuel[1]:
            return JsonResponse({"success": False, "error": "Exécutez le SQL des priorités avant de les enregistrer."}, status=503)
        if donnees.get("original") != actuel[0][circuit]:
            return JsonResponse({"success": False, "error": "Les priorités ont changé depuis leur chargement. Rechargez avant d’enregistrer."}, status=409)
        ActionsPriorites.objects.update_or_create(code=circuit, defaults={"niveaux": ordre})
    return JsonResponse({"success": True})


@api(["POST"])
def enregistrer_configuration(request):
    donnees = lire_json(request)
    circuit = circuit_valide(donnees["circuit"])
    scope = verifier_scope(donnees["scope"])
    verifier_contexte(circuit, scope)
    if niveau_regle(circuit, scope) is None:
        raise ValueError("Cette combinaison ne correspond à aucun niveau de priorité.")
    original = donnees.get("original")
    ancien_scope = verifier_scope(original["scope"]) if original else scope
    actions = donnees.get("actions", [])
    suppression = donnees.get("supprimer") is True
    if not isinstance(actions, list) or len(actions) > 200:
        raise ValueError("La liste d’actions est invalide.")
    actions = {identifiant(valeur) for valeur in actions}
    if suppression and not original:
        raise ValueError("Sélectionnez la configuration à supprimer.")
    if not suppression and not actions:
        raise ValueError("Choisissez au moins une action.")
    if actions - set(ChangementEtape.objects.filter(pk__in=actions).values_list("pk", flat=True)):
        raise ValueError("Une action sélectionnée n’existe plus.")
    try:
        with transaction.atomic():
            # Sérialise les éditions d'une même étape, y compris une création.
            verrouiller([scope["id_etape_id"], ancien_scope["id_etape_id"]])
            lignes = list(ActionsPossibles.objects.select_for_update().filter(**ancien_scope))
            if original and original.get("signature") != signature(lignes):
                return JsonResponse({"success": False, "error": "Cette configuration a changé. Rechargez-la avant de l’enregistrer."}, status=409)
            if (not original and lignes) or (scope != ancien_scope and ActionsPossibles.objects.filter(**scope).exists()):
                return JsonResponse({"success": False, "error": "Une configuration possède déjà ces critères. Modifiez-la plutôt que d’en créer une seconde."}, status=409)
            if not suppression:
                deja_configurees = {ligne.id_changement_etape_id for ligne in lignes} if scope == ancien_scope else set()
                nouvelles = actions - deja_configurees
                catalogue_actions = charger_actions()
                par_id = {action.pk: action for action in catalogue_actions}
                etape = EtapeDossier.objects.get(pk=scope["id_etape_id"])
                for pk in nouvelles:
                    action = par_id.get(pk)
                    if action is None:
                        raise ValueError("Une action sélectionnée n’existe plus.")
                    autorise, raison, _ = disponibilite(action, circuit, etape.etape)
                    if not autorise:
                        raise ValueError(f"{action.action} : {raison}")
            if suppression:
                ActionsPossibles.objects.filter(pk__in=[ligne.pk for ligne in lignes]).delete()
            else:
                conserves = set()
                for ligne in lignes:
                    if ligne.id_changement_etape_id not in actions:
                        ligne.delete()
                    else:
                        if scope != ancien_scope:
                            for cle, valeur in scope.items():
                                setattr(ligne, cle, valeur)
                            ligne.save(update_fields=[cle.removesuffix("_id") if cle.startswith("id_") else cle for cle in scope])
                        conserves.add(ligne.id_changement_etape_id)
                for action_id in sorted(actions - conserves):
                    ActionsPossibles.objects.create(**scope, id_changement_etape_id=action_id)
    except IntegrityError:
        return JsonResponse({"success": False, "error": "La base refuse cette combinaison de critères (contrainte existante). Aucune modification n’a été conservée."}, status=400)
    return JsonResponse({"success": True})


@api(["POST"])
def tester(request):
    donnees = lire_json(request)
    circuit = circuit_valide(donnees["circuit"])
    if donnees.get("numero"):
        numero = str(donnees["numero"]).strip()
        if not numero.isdecimal() or len(numero) > 15:
            raise ValueError("Numéro de dossier invalide.")
        if circuit == "dm":
            dossier = DossierManifSportive.objects.filter(numero_dossier_declaration_manifestations=numero).first()
            if not dossier:
                raise ValueError("Dossier DM introuvable.")
            circuit, contexte = contexte_dm(dossier)
        else:
            dossier = Dossier.objects.select_related("id_demarche").filter(numero=numero).first()
            if not dossier:
                raise ValueError("Dossier DN introuvable.")
            circuit, contexte = contexte_dossier(dossier)
        if not donnees.get("etape_fictive"):
            raise ValueError("Choisissez l’étape fictive du dossier à tester.")
        contexte["id_etape_id"] = identifiant(donnees["etape_fictive"])
        contexte = verifier_scope(contexte)
    else:
        contexte = verifier_scope(donnees["contexte"])
        verifier_contexte(circuit, contexte)
        if contexte["id_demarche_id"] is None:
            raise ValueError("Choisissez la démarche du dossier à simuler.")
        if circuit != "dn" and contexte["type_manif_sportive"] is None:
            raise ValueError("Choisissez la démarche et le type du dossier sportif à simuler.")
    resultat = evaluer_actions(circuit, contexte)
    gagnant = resultat.get("niveau_retenu")
    resultat["configuration_retenue"] = filtres_niveau(circuit, gagnant["code"], contexte) if gagnant else None
    catalogue_actions = charger_actions(resultat.get("actions", []))
    etape = EtapeDossier.objects.get(pk=contexte["id_etape_id"])
    par_label = {action.action: action for action in catalogue_actions}
    compatibles, incompatibles = [], []
    for label in resultat.get("actions", []):
        action = par_label.get(label)
        autorise, raison, _ = disponibilite(action, circuit, etape.etape) if action else (False, "Action inconnue.", None)
        (compatibles if autorise else incompatibles).append(label if autorise else {"nom": label, "raison": raison})
    resultat["actions_selectionnees"] = resultat.get("actions", [])
    resultat["actions"], resultat["actions_incompatibles"] = compatibles, incompatibles
    return JsonResponse({"success": True, "circuit": circuit, "contexte": contexte, **resultat})


@api(["GET"])
def rechercher_dossiers(request):
    """Autocomplétion bornée au circuit courant, sans chargement de formulaire."""
    circuit = circuit_valide(request.GET.get("circuit"))
    recherche = (request.GET.get("q") or "").strip()
    if not recherche.isascii() or not recherche.isdecimal() or not 1 <= len(recherche) <= 15:
        return JsonResponse({"success": True, "dossiers": []})
    if circuit == "dm":
        queryset = DossierManifSportive.objects.exclude(
            pk__in=DossierManifestationLiaison.objects.values("id_dossier_manif_id"),
        ).select_related("id_etape")
        numero, etape = "numero_dossier_declaration_manifestations", "id_etape"
    else:
        queryset = Dossier.objects.select_related("id_etape_dossier")
        if circuit == "sportif":
            queryset = queryset.filter(id_demarche__type="Manifestations sportives")
        else:
            queryset = queryset.exclude(id_demarche__type="Manifestations sportives")
        numero, etape = "numero", "id_etape_dossier"
    dossiers = queryset.annotate(numero_texte=Cast(numero, output_field=CharField())).filter(
        numero_texte__startswith=recherche,
    ).order_by(numero)[:12]
    return JsonResponse({"success": True, "dossiers": [
        {"numero": str(getattr(dossier, numero)), "etape": getattr(dossier, f"{etape}_id"),
         "etape_nom": getattr(dossier, etape).etape,
         "nom": dossier.nom_dossier or ""} for dossier in dossiers
    ]})
