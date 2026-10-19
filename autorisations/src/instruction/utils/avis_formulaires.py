"""Configuration déclarative des formulaires de demande et d'import d'avis.

Les conditions portent uniquement sur les sélecteurs structurants. Pas de code
exécutable, ni de dépendance entre les champs configurés.
"""
from copy import deepcopy
from string import Formatter

from django.core.exceptions import ValidationError
from django.forms import DateTimeField

from autorisations.models.models_avis import AvisFormulaireConfiguration


CONTEXTES = {"dossier": "Depuis un dossier", "generique": "Demande générique", "existant": "Ajouter un avis existant"}
LIBELLES = {
    "nature": "Nature de l'avis", "expert_externe": "Choix de l'expert externe",
    "expert_interne": "Choix de l'expert interne", "destinataire": "Destinataire",
    "demarche": "Type de demande", "thematique": "Thématique de l'avis",
    "note_demandeur": "Note", "pj_demande_avis": "Joindre le projet d'avis de l'instance (Word)",
    "pj_projet_acte": "Joindre le projet d'acte (Word, PDF)", "pj_rapport_cs": "Joindre le rapport d'avis du CS (PDF)",
    "pj_lie_avis": "Autres pièce(s) jointe(s) liée(s) à l'avis", "formulation_avis": "Formulation de l'avis",
}
FICHIERS = {"pj_demande_avis": "id_projet_avis", "pj_projet_acte": "id_projet_acte", "pj_rapport_cs": "id_rapport_instance", "pj_lie_avis": None}
STRUCTURELS = {"nature", "thematique", "demarche", "expert_interne", "expert_externe", "demandeur_avis"}
CHOIX_IMPORT = {
    "mode_contact": (("Courrier papier", "Courrier papier"), ("Téléphone", "Téléphone"), ("Mail", "Mail"), ("Autre", "Autre")),
    "publication_raa": (("a_publier", "À publier"), ("deja_publie", "Déjà publié"), ("non_requise", "Publication non requise")),
    "reponse": (("favorable", "Favorable"), ("favorable_sous_reserve", "Favorable sous réserve"),
                ("defavorable", "Défavorable"), ("absence_avis_en_etat", "Absence d’avis en l’état")),
}
LIBELLES_IMPORT = {
    "nature": LIBELLES["nature"], "demandeur_avis": "Instructeur.rice à l'origine de la demande",
    "expert_interne": "Expert interne", "expert_externe": "Expert externe",
    "numero_avis_externe": "Numéro de l'avis CS importé", "publication_raa": "Publication au RAA",
    "thematique": LIBELLES["thematique"], "mode_contact": "Expert.e sollicité.e via", "reponse": "Réponse de l'avis",
    "date_demande_avis": "Date de la demande d'avis", "date_reponse_avis": "Date de la réponse de l'expert.e",
    "note_demandeur": "Note", "pj_lie_avis": "Pièce(s) jointe(s) liée(s) à l'avis",
}
SOURCES_CONDITIONS = {"nature_type", "expert_interne", "expert_externe", "expert_cs", "demarche"}
VARIABLES = {"numero_dossier", "numero_avis", "type_demarche"}


def critere(champ, valeur, operateur="egal"):
    return {"champ": champ, "operateur": operateur, "valeur": valeur}


def regle(conditions, **effets):
    return {"conditions": conditions, **effets}


def configuration_standard(contexte):
    if contexte not in CONTEXTES:
        raise ValidationError("Contexte de formulaire inconnu.")
    resultat = []
    instance = critere("nature_type", "instance")
    interne = critere("nature_type", "interne")
    choisie = critere("nature_type", "", "renseigne")
    for code, libelle in (LIBELLES_IMPORT if contexte == "existant" else LIBELLES).items():
        if code == "demarche" and contexte == "dossier":
            continue
        champ = dict(code=code, ordre=len(resultat), libelle=libelle, aide="", visible=False,
                     requis_brouillon=False, requis_envoi=False, defaut="", placeholder="",
                     choix_autorises=None, regles=[])
        if code == "note_demandeur":
            champ["placeholder"] = "Note libre..." if contexte == "existant" else "Note libre pour le demandeur…"
        if code == "numero_avis_externe":
            champ.update(placeholder="Ex. CS-2026-042", aide="Si ce champ n’est pas rempli, l’avis se verra attribuer un numéro par défaut.")
        if contexte == "existant" and code not in {"expert_interne", "expert_externe"}:
            champ.update(visible=True, requis_envoi=code not in {"note_demandeur", "pj_lie_avis", "numero_avis_externe"})
            if code in {"numero_avis_externe", "publication_raa"}:
                champ.update(visible=False, requis_envoi=False,
                    regles=[regle([instance, critere("expert_cs", "true")], visible=True,
                                  requis_envoi=code == "publication_raa", defaut="a_publier" if code == "publication_raa" else "")])
            if code == "reponse":
                champ["defaut"] = "favorable"
        elif code in {"nature", "thematique", "demarche"}:
            champ.update(visible=True, requis_brouillon=True, requis_envoi=True)
        elif code in {"expert_interne", "expert_externe"}:
            champ["regles"] = [regle([interne if code == "expert_interne" else instance], visible=True, requis_brouillon=True, requis_envoi=True)]
        elif code == "destinataire":
            champ["regles"] = [regle([instance, critere("expert_cs", "true")], visible=True, requis_envoi=True, defaut="CS")]
        elif code in {"pj_demande_avis", "pj_projet_acte", "pj_rapport_cs"}:
            champ["regles"] = [regle([instance], visible=True, requis_envoi=code != "pj_rapport_cs")]
        elif code == "pj_lie_avis":
            champ["regles"] = [regle([interne], visible=True, libelle="Pièces jointes à transmettre"), regle([instance], visible=True)]
        elif code == "formulation_avis":
            texte_interne = ("Bonjour, je sollicite votre avis sur le dossier {numero_dossier}…" if contexte == "dossier"
                             else "Bonjour,\n\nJe vous consulte car [saisir la raison].\n\nMerci d’avance pour votre retour.")
            texte_instance = ("Bonjour, vous trouverez ci-joint la demande d'avis associée au dossier." if contexte == "dossier"
                              else "Bonjour, vous trouverez ci-joint la demande d'avis.")
            champ["regles"] = [regle([interne], visible=True, requis_envoi=True, defaut=texte_interne),
                               regle([instance], visible=True, requis_envoi=True, defaut=texte_instance)]
        else:
            champ["regles"] = [regle([choisie], visible=True)]
        resultat.append(champ)
    if contexte == "existant":
        for champ in resultat:
            champ["requis_brouillon"] = False  # L'import ne crée pas de brouillon.
            for cas in champ["regles"]:
                if "requis_brouillon" in cas:
                    cas["requis_brouillon"] = False
    return deepcopy(resultat)


def charger_configuration(contexte):
    # Un chargement par requête ; aucune écriture implicite ni accès à une BDD externe.
    configuration = AvisFormulaireConfiguration.objects.filter(code=contexte).prefetch_related("champs").first()
    standards = {champ["code"]: champ for champ in configuration_standard(contexte)}
    if configuration:
        for champ in configuration.champs.all():
            if champ.code in standards:
                standards[champ.code] = {cle: getattr(champ, cle) for cle in standards[champ.code]}
    # Le catalogue AvisThematique est désormais l'unique source des listes.
    standards["thematique"]["choix_autorises"] = None
    for cas in standards["thematique"]["regles"]:
        cas.pop("choix_autorises", None)
    return sorted(standards.values(), key=lambda champ: (champ["ordre"], champ["code"]))


def correspond(condition, etat):
    valeur = str(etat.get(condition["champ"], "") or "")
    attendue = condition.get("valeur", "")
    operation = condition["operateur"]
    if operation == "renseigne":
        return bool(valeur)
    if operation == "vide":
        return not valeur
    if operation == "dans":
        return valeur in attendue
    return valeur == str(attendue)


def evaluer_configuration(configuration, etat, variables=None):
    resultat = {}
    for champ in configuration:
        effectif = deepcopy(champ)
        for cas in champ["regles"]:
            if all(correspond(condition, etat) for condition in cas["conditions"]):
                effectif.update({cle: valeur for cle, valeur in cas.items() if cle != "conditions" and not (cle in {"libelle", "placeholder"} and not valeur.strip())})
                break
        if variables is not None:
            effectif["defaut"] = effectif["defaut"].format_map({cle: str(variables.get(cle, "") or "") for cle in VARIABLES})
        resultat[champ["code"]] = effectif
    return resultat


def verifier_configuration(contexte, champs):
    """Valide les données administrateur et les garde-fous avant toute écriture."""
    standards = {c["code"]: c for c in configuration_standard(contexte)}
    if not isinstance(champs, list) or len(champs) != len(standards) or {c.get("code") for c in champs if isinstance(c, dict)} != set(standards):
        raise ValidationError("La liste des champs du formulaire est incomplète ou invalide.")
    resultat = []
    for ordre, brut in enumerate(champs):
        if not isinstance(brut, dict):
            raise ValidationError("Champ invalide.")
        code = brut["code"]
        champ = {cle: brut.get(cle, defaut) for cle, defaut in standards[code].items()}
        champ["ordre"] = ordre
        if code == "thematique":
            champ["choix_autorises"] = None
            if isinstance(champ["regles"], list):
                champ["regles"] = [{cle: valeur for cle, valeur in cas.items() if cle != "choix_autorises"}
                                   if isinstance(cas, dict) else cas for cas in champ["regles"]]
        if not isinstance(champ["libelle"], str) or not champ["libelle"].strip() or len(champ["libelle"]) > 180:
            raise ValidationError("Chaque champ doit avoir un libellé (180 caractères maximum).")
        if not isinstance(champ["aide"], str) or len(champ["aide"]) > 2000:
            raise ValidationError("Texte d'aide invalide (2 000 caractères maximum).")
        if not isinstance(champ["regles"], list) or len(champ["regles"]) > 20:
            raise ValidationError("Un champ peut avoir au maximum 20 cas conditionnels.")
        variantes = [champ]
        for indice, cas in enumerate(champ["regles"]):
            if not isinstance(cas, dict) or set(cas) - {"conditions", "visible", "requis_brouillon", "requis_envoi", "defaut", "libelle", "placeholder", "choix_autorises"}:
                raise ValidationError("Cas conditionnel invalide.")
            cas = {cle: valeur for cle, valeur in cas.items()
                   if not (cle in {"libelle", "placeholder"} and isinstance(valeur, str) and not valeur.strip())}
            champ["regles"][indice] = cas
            conditions = cas.get("conditions")
            if not isinstance(conditions, list) or not 1 <= len(conditions) <= 5:
                raise ValidationError("Un cas doit contenir entre 1 et 5 conditions.")
            for condition in conditions:
                if not isinstance(condition, dict) or condition.get("champ") not in SOURCES_CONDITIONS or condition.get("operateur") not in {"egal", "dans", "renseigne", "vide"}:
                    raise ValidationError("Condition inconnue.")
                valeur = condition.get("valeur", "")
                if condition["operateur"] == "dans":
                    if not isinstance(valeur, list) or not 1 <= len(valeur) <= 100 or any(not isinstance(v, str) or len(v) > 100 for v in valeur):
                        raise ValidationError("Liste de valeurs invalide.")
                elif not isinstance(valeur, str) or len(valeur) > 100:
                    raise ValidationError("Valeur de condition invalide.")
            variantes.append({**champ, **cas})
        for variante in variantes:
            if not isinstance(variante["placeholder"], str) or len(variante["placeholder"]) > 2000:
                raise ValidationError("Texte indicatif invalide (2 000 caractères maximum).")
            choix = variante["choix_autorises"]
            if choix is not None and (code != "thematique" or not isinstance(choix, list) or len(choix) > 500
                    or any(not isinstance(v, str) or not v.isdecimal() or len(v) > 10 for v in choix) or len(set(choix)) != len(choix)):
                raise ValidationError("Liste de thématiques autorisées invalide.")
            if any(type(variante[cle]) is not bool for cle in ("visible", "requis_brouillon", "requis_envoi")):
                raise ValidationError("Visibilité et obligations doivent être des booléens.")
            if not variante["visible"] and (variante["requis_brouillon"] or variante["requis_envoi"]):
                raise ValidationError(f"{champ['libelle']} : un champ masqué ne peut pas être obligatoire.")
            valeur = variante["defaut"]
            if not isinstance(valeur, str) or len(valeur) > 10000 or (code in FICHIERS and valeur):
                raise ValidationError("Valeur initiale invalide (aucun fichier ne peut être prérempli).")
            if code in CHOIX_IMPORT and valeur and valeur not in dict(CHOIX_IMPORT[code]):
                raise ValidationError(f"Valeur initiale inconnue pour {champ['libelle']}.")
            if code == "numero_avis_externe" and len(valeur) > 100:
                raise ValidationError("Le numéro externe ne doit pas dépasser 100 caractères.")
            if code in {"date_demande_avis", "date_reponse_avis"} and valeur:
                DateTimeField().clean(valeur)
            try:
                if any(nom not in VARIABLES or formatage or conversion for _, nom, formatage, conversion in Formatter().parse(valeur) if nom is not None):
                    raise ValueError()
            except ValueError:
                raise ValidationError("Variables autorisées : {numero_dossier}, {numero_avis}, {type_demarche}.")
            if not isinstance(variante["libelle"], str) or not variante["libelle"].strip() or len(variante["libelle"]) > 180:
                raise ValidationError("Libellé conditionnel invalide.")
        # Les sélecteurs nécessaires à la structure d'un avis restent protégés.
        if code == "thematique":
            if any(variante[cle] != standards[code][cle] for variante in variantes for cle in ("visible", "requis_brouillon", "requis_envoi")):
                raise ValidationError("La thématique doit rester visible et obligatoire.")
        elif code in STRUCTURELS:
            if any(champ[cle] != standards[code][cle] for cle in ("visible", "requis_brouillon", "requis_envoi", "regles")):
                raise ValidationError(f"Les règles structurelles de {champ['libelle']} ne peuvent pas être retirées.")
        resultat.append(champ)
    return resultat
