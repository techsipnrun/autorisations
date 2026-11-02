"""Sélection commune aux dossiers réels et au simulateur, sans effet de bord."""
import logging

from django.db import OperationalError, ProgrammingError, transaction

from autorisations.models.models_instruction import (
    ActionsPossibles, ActionsPriorites, Demarche, DossierManifestationLiaison,
)

logger = logging.getLogger("ORM_DJANGO")
CRITERES = ("id_demarche_id", "id_groupe_instructeur_id", "coeur_de_parc", "type_manif_sportive")
PROFILS = {
    "dn": {
        "nom": "Dossiers DN · hors manifestations sportives",
        "niveaux": [
            ("groupe_demarche", "Groupe + démarche", ("id_demarche_id", "id_groupe_instructeur_id")),
            ("demarche", "Démarche", ("id_demarche_id",)),
            ("general", "Configuration générale", ()),
        ],
    },
    "sportif": {
        "nom": "Manifestations sportives · DN seul ou lié à DM",
        "niveaux": [
            ("groupe_coeur", "Groupe + démarche + type + cœur de parc", CRITERES),
            ("demarche_coeur", "Démarche + type + cœur de parc", ("id_demarche_id", "type_manif_sportive", "coeur_de_parc")),
            ("demarche_type", "Démarche + type", ("id_demarche_id", "type_manif_sportive")),
            ("type", "Type de dossier sportif", ("type_manif_sportive",)),
            ("general", "Configuration générale", ()),
        ],
    },
    "dm": {
        "nom": "Dossiers DM seuls · sans liaison DN",
        "niveaux": [
            ("demarche_coeur", "Cœur de parc", ("id_demarche_id", "type_manif_sportive", "coeur_de_parc")),
            # Le repli général DM est explicitement typé ; les règles DN
            # absentes de la plateforme gardent leur type vide.
            ("general", "Configuration générale", ("type_manif_sportive",)),
        ],
    },
}


def verifier_ordre(circuit, ordre):
    attendus = [code for code, _, _ in PROFILS[circuit]["niveaux"]]
    if not isinstance(ordre, list) or any(not isinstance(code, str) for code in ordre):
        raise ValueError("L’ordre des priorités doit être une liste de niveaux.")
    if len(ordre) != len(attendus) or set(ordre) != set(attendus):
        raise ValueError("Chaque niveau existant doit apparaître exactement une fois.")
    return ordre


def charger_ordres():
    ordres = {circuit: [code for code, _, _ in profil["niveaux"]] for circuit, profil in PROFILS.items()}
    # Un déploiement avant le SQL doit laisser les dossiers utilisables. Le
    # savepoint évite d'invalider une éventuelle transaction appelante.
    try:
        with transaction.atomic():
            configurations = list(ActionsPriorites.objects.all())
    except (ProgrammingError, OperationalError):
        logger.debug("Priorités non installées : utilisation des pyramides standards.")
        return ordres, False
    for configuration in configurations:
        if configuration.code not in PROFILS:
            continue
        try:
            ordre = configuration.niveaux
            # Relire les anciens ordres DM sans réécrire les personnalisations.
            if (configuration.code == "dm" and isinstance(ordre, list)
                    and all(isinstance(code, str) for code in ordre)
                    and len(ordre) == len(set(ordre))):
                ordre = [code for code in ordre if code not in ("demarche", "demarche_type")]
            ordres[configuration.code] = verifier_ordre(configuration.code, ordre)
        except ValueError:
            logger.warning("Ordre des actions invalide pour %s : ordre standard conservé.", configuration.code)
    return ordres, True


def ordonner_labels(labels):
    return sorted(dict.fromkeys(labels), key=lambda label: 2 if label == "Classer comme annulé" else 1 if label.startswith("Archiver ") else 0)


def contexte_dossier(dossier):
    contexte = {"id_etape_id": dossier.id_etape_dossier_id, "id_demarche_id": dossier.id_demarche_id,
                "id_groupe_instructeur_id": dossier.id_groupeinstructeur_id, "present_sur_dn": dossier.present_sur_ds,
                "coeur_de_parc": None, "type_manif_sportive": None}
    circuit = "dn"
    if dossier.id_demarche.type == "Manifestations sportives":
        circuit = "sportif"
        liaison = DossierManifestationLiaison.objects.filter(id_dossier=dossier).first()
        contexte["type_manif_sportive"] = "Dossier complet" if liaison else "Dossier DN"
        contexte["coeur_de_parc"] = liaison.id_dossier_manif.coeur_de_parc if liaison else None
    return circuit, contexte


def contexte_dm(dossier):
    if DossierManifestationLiaison.objects.filter(id_dossier_manif=dossier).exists():
        raise ValueError("Ce dossier DM est lié à un DN : utilisez le circuit du dossier DN.")
    return "dm", {"id_etape_id": dossier.id_etape_id,
                  "id_demarche_id": Demarche.objects.get(type="Manifestations sportives").pk,
                  "id_groupe_instructeur_id": None, "present_sur_dn": False,
                  "coeur_de_parc": dossier.coeur_de_parc, "type_manif_sportive": "Dossier DM"}


def scope_regle(regle):
    return {cle: getattr(regle, cle) for cle in ("id_etape_id", "present_sur_dn", *CRITERES)}


def niveau_regle(circuit, scope):
    """Classe une règle par sa forme, sans inventer de combinaison nouvelle."""
    presents = {cle for cle in CRITERES if scope.get(cle) is not None}
    for code, _, champs in PROFILS[circuit]["niveaux"]:
        if presents == set(champs):
            return code
    return None


def filtres_niveau(circuit, code, contexte):
    champs = next(champs for cle, _, champs in PROFILS[circuit]["niveaux"] if cle == code)
    # False (hors cœur) est une valeur connue, contrairement à None.
    if any(contexte.get(champ) is None for champ in champs):
        return None
    return {"id_etape_id": contexte["id_etape_id"], "present_sur_dn": contexte["present_sur_dn"],
            **{champ: contexte.get(champ) if champ in champs else None for champ in CRITERES}}


def evaluer_actions(circuit, contexte, *, ordre=None, regles=None):
    if ordre is None:
        ordre = charger_ordres()[0][circuit]
    verifier_ordre(circuit, ordre)
    if regles is None:
        regles = list(ActionsPossibles.objects.filter(id_etape_id=contexte["id_etape_id"])
                      .select_related("id_changement_etape"))
    traces, labels, retenus, gagnant = [], [], [], None
    niveaux = {code: nom for code, nom, _ in PROFILS[circuit]["niveaux"]}
    for position, code in enumerate(ordre, 1):
        filtres = filtres_niveau(circuit, code, contexte)
        correspondances = [regle for regle in regles if all(getattr(regle, cle) == valeur for cle, valeur in filtres.items())] if filtres else []
        statut = "inapplicable" if filtres is None else "absente"
        if correspondances:
            statut = "ecartee" if gagnant else "retenue"
            if not gagnant:
                gagnant = {"code": code, "nom": niveaux[code], "priorite": position}
                labels = ordonner_labels([regle.id_changement_etape.action for regle in correspondances])
                retenus = [regle.pk for regle in correspondances]
        traces.append({"code": code, "nom": niveaux[code], "priorite": position, "statut": statut,
                       "regles": [regle.pk for regle in correspondances],
                       "actions": ordonner_labels([regle.id_changement_etape.action for regle in correspondances])})
    return {"actions": labels, "regles_retenues": retenus, "niveau_retenu": gagnant, "niveaux": traces}
