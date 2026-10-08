"""Composition des noms DN à partir de règles ordonnées, sans requête BDD."""

from datetime import date, datetime
import re

from django.utils import timezone
from autorisations.models.models_instruction import DossierManifSportive
from synchronisation.utils.date_activite import parser_date_activite


ATTRIBUTS_NOM_DOSSIER = {
    "dossier.numero": "Dossier · Numéro",
    "dossier.date_depot": "Dossier · Date de dépôt",
    **{
        f"{role}.{attribut}": f"{libelle} · {nom}"
        for role, libelle in [("demandeur", "Demandeur"), ("beneficiaire", "Bénéficiaire")]
        for attribut, nom in [
            ("prenom", "Prénom"), ("nom", "Nom"),
            ("raison_sociale", "Raison sociale"), ("organisation", "Organisation"),
        ]
    },
}
TRANSFORMATIONS_NOM_DOSSIER = {
    "aucune": "Aucune", "majuscules": "MAJUSCULES", "minuscules": "minuscules",
    "date": "Date · JJ/MM/AAAA", "date_heure": "Date et heure · JJ/MM/AAAA HHhMM",
    "personnalisee": "Personnalisée",
}


CHAMPS_DM_NOM_DOSSIER_EXCLUS = {
    "id", "id_etape", "geometrie", "emplacement", "archive",
    "id_groupeinstructeur", "numero_dossier_declaration_manifestations",
}


def champs_dm_nommage_autorises():
    """Champs DM unitaires proposés pour le nommage des manifestations sportives."""
    return [
        champ for champ in DossierManifSportive._meta.fields
        if champ.name not in CHAMPS_DM_NOM_DOSSIER_EXCLUS
        and champ.get_internal_type() not in {"JSONField", "ArrayField"}
    ]


def construire_contexte_nommage(dossier, contacts, dossier_champs, dossier_dm=None):
    beneficiaire = contacts.get("beneficiaire") or {}
    demandeur = contacts.get("demandeur_intermediaire") or beneficiaire
    attributs = {
        "dossier.numero": dossier.get("numero"),
        "dossier.date_depot": dossier.get("date_depot"),
    }
    for role, contact in [("beneficiaire", beneficiaire), ("demandeur", demandeur)]:
        for champ in ("prenom", "nom", "raison_sociale", "organisation"):
            attributs[f"{role}.{champ}"] = contact.get(champ)
    return {
        "attributs": attributs,
        "champs": {
            str(item["champ"]["id_ds"]): item["champ"].get("valeur")
            for item in dossier_champs if item.get("champ", {}).get("id_ds") is not None
        },
        "champs_dm": dossier_dm or {},
    }


def cle_correspondance_nommage(valeur):
    """Comparaison exacte sans tenir compte de la casse ni des espaces superflus."""
    texte = re.sub(r"\s+", " ", str(valeur)).strip().casefold()
    return {"true": "oui", "false": "non"}.get(texte, texte)


def transformer_valeur(valeur, transformation, configuration=None):
    if valeur is None or isinstance(valeur, (list, dict, tuple, set)):
        return None
    if isinstance(valeur, str) and not valeur.strip():
        return None
    if transformation not in TRANSFORMATIONS_NOM_DOSSIER:
        return None
    if transformation == "personnalisee":
        texte = transformer_valeur(valeur, "aucune")
        if texte is None:
            return None
        configuration = configuration or {}
        if not isinstance(configuration, dict):
            return None
        correspondances = configuration.get("correspondances")
        if not isinstance(correspondances, list) or not correspondances:
            return None
        for correspondance in correspondances:
            if (not isinstance(correspondance, dict)
                    or not isinstance(correspondance.get("valeur"), str)
                    or not isinstance(correspondance.get("texte"), str)):
                return None
            if cle_correspondance_nommage(texte) == cle_correspondance_nommage(correspondance["valeur"]):
                return correspondance["texte"].strip()
        return texte if configuration.get("sans_correspondance", "conserver") == "conserver" else None
    if transformation in {"date", "date_heure"}:
        try:
            valeur = valeur if isinstance(valeur, (date, datetime)) else parser_date_activite(str(valeur).strip())
        except (TypeError, ValueError, OverflowError):
            return None
        if isinstance(valeur, datetime) and timezone.is_aware(valeur):
            valeur = timezone.localtime(valeur)
        if transformation == "date_heure" and not isinstance(valeur, datetime):
            return None
        return valeur.strftime("%d/%m/%Y" if transformation == "date" else "%d/%m/%Y %Hh%M")
    if isinstance(valeur, bool):
        texte = "Oui" if valeur else "Non"
    elif isinstance(valeur, (date, datetime)):
        return transformer_valeur(valeur, "date")
    else:
        texte = str(valeur).strip()
    if transformation == "majuscules":
        return texte.upper()
    if transformation == "minuscules":
        return texte.lower()
    return texte


def evaluer_regle_nom_dossier(regle, contexte):
    morceaux, manquants = [], []
    for element in regle["elements"]:
        if element["type"] == "texte":
            # Les séparateurs entre éléments sont gérés ici, afin que la
            # configuration reste lisible : « Gîte », « à », « Mafate ».
            texte_fixe = (element.get("texte") or "").strip()
            if texte_fixe:
                morceaux.append(texte_fixe)
            continue
        if element["type"] == "champ_dn":
            valeur = contexte["champs"].get(str(element["id_ds"]))
        elif element["type"] == "champ_dm":
            valeur = contexte["champs_dm"].get(element["champ_dm"])
        else:
            valeur = contexte["attributs"].get(element["attribut"])
        texte = transformer_valeur(
            valeur, element.get("transformation", "aucune"), element.get("configuration_transformation"),
        )
        if texte is None:
            manquants.append(element["libelle"])
        else:
            morceaux.append(texte)
    nom = re.sub(r"\s+", " ", " ".join(morceaux)).strip()
    return (None if manquants or not nom else nom), list(dict.fromkeys(manquants))


def generer_nom_dossier(regles, contexte, expliquer=False):
    """Retourne None si aucune règle complète ; les noms manuel/standard restent intacts."""
    details, nom_genere, regle_retenue = [], None, None
    for regle in regles:
        if not regle.get("actif", True):
            if expliquer:
                details.append({"ordre": regle["ordre"], "libelle": regle["libelle"], "statut": "désactivée"})
            continue
        nom, manquants = evaluer_regle_nom_dossier(regle, contexte)
        if expliquer:
            details.append({
                "ordre": regle["ordre"], "libelle": regle["libelle"],
                "statut": "retenue" if nom else "ignorée", "manquants": manquants,
            })
        if nom is not None:
            nom_genere, regle_retenue = nom, regle["ordre"]
            break
    return {"nom_genere": nom_genere, "regle_retenue": regle_retenue, "details": details}


def compiler_regles_nommage(regles):
    """Compile une configuration préchargée une seule fois pour toute la démarche."""
    labels_dm = {champ.name: str(champ.verbose_name).capitalize() for champ in champs_dm_nommage_autorises()}
    return [{
        "libelle": regle.libelle, "ordre": regle.ordre, "actif": regle.actif,
        "elements": [{
            "type": element.type_element, "texte": element.texte or "",
            "id_champ": element.id_champ_id,
            "id_ds": element.id_champ.id_ds if element.id_champ_id else None,
            "champ_dm": element.champ_dm,
            "attribut": element.attribut, "transformation": element.transformation,
            "configuration_transformation": element.configuration_transformation,
            "libelle": (
                element.id_champ.nom if element.id_champ_id
                else labels_dm.get(element.champ_dm, element.champ_dm) if element.type_element == "champ_dm"
                else ATTRIBUTS_NOM_DOSSIER.get(element.attribut, "Texte")
            ),
        } for element in regle.elements.all()],
    } for regle in regles]
