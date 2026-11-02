"""Disponibilité et rendu des actions : les composants sont la source de vérité."""
import re

from django.template import TemplateDoesNotExist
from django.template.loader import get_template

from autorisations.models.models_instruction import ChangementEtape

CIRCUITS = ("dn", "sportif", "dm")


def interface_etape(circuit, etape):
    """Écran habituel : réception DN, instruction DN, ou DM seul."""
    return "dm" if circuit == "dm" else "preinstruction" if etape == "À affecter" else "instruction"


def fragment_action(action, interface):
    code = getattr(action, "code", None)
    if not isinstance(code, str) or not re.fullmatch(r"[a-z][a-z0-9_]*", code):
        return None, "Code technique absent ou invalide : cette action doit être raccordée à l’application."
    chemin = f"instruction/refacto/actions/{interface}/{code}.html"
    try:
        get_template(chemin)
        return chemin, ""
    except TemplateDoesNotExist:
        return None, "Aucun composant d’action n’est implémenté sur l’écran correspondant à cette étape."


def formulaire_action(code):
    """Le formulaire associé au code est chargé automatiquement sur les écrans DN."""
    chemin = f"instruction/refacto/actions/formulaires/{code}.html"
    try:
        get_template(chemin)
    except TemplateDoesNotExist:
        return None
    return chemin


def charger_actions(labels=None):
    queryset = ChangementEtape.objects.order_by("action")
    if labels is not None:
        queryset = queryset.filter(action__in=labels)
    return list(queryset)


def disponibilite(action, circuit, etape, *, interface=None, fragments=None):
    interface_cible = interface_etape(circuit, etape)
    technique = fragments if fragments is not None else {
        nom: fragment_action(action, nom) for nom in {interface_cible, interface or interface_cible}
    }
    fragment, raison = technique[interface_cible]
    if not fragment:
        return False, raison, None
    if interface:
        fragment, raison = technique[interface]
        if not fragment:
            return False, raison, None
    return True, "", fragment


def construire_menu(actions, labels, circuit, etape, interface):
    par_label = {action.action: action for action in actions}
    resultat = []
    for label in labels:
        action = par_label.get(label)
        if not action:
            continue
        presente, _, fragment = disponibilite(action, circuit, etape, interface=interface)
        if presente:
            resultat.append({"code": action.code, "label": action.action, "template": fragment,
                             "url_name": f"{action.code}_url", "interface": interface,
                             "formulaire": formulaire_action(action.code) if interface != "dm" else None})
    return resultat


def preparer_menu(labels, dossier, interface):
    if not labels:
        return []
    if interface == "dm":
        circuit, etape_obj = "dm", dossier.id_etape
    else:
        circuit = "sportif" if dossier.id_demarche.type == "Manifestations sportives" else "dn"
        etape_obj = dossier.id_etape_dossier
    return construire_menu(charger_actions(labels), labels, circuit, etape_obj.etape, interface)
