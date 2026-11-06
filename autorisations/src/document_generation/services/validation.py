"""Validation métier pure : aucun accès BDD, NAS ou rendu de document."""

from collections.abc import Mapping

from autorisations.models.models_generation import Balise


ABSENT = object()


def valeur_vide(value):
    """False et 0 sont des valeurs ; seuls les contenus absents sont vides."""
    return (
        value is ABSENT or value is None
        or (isinstance(value, str) and not value.strip())
        or (isinstance(value, (list, tuple, dict, set)) and len(value) == 0)
    )


def lire_contexte(context, code):
    node = context
    for part in code.split("."):
        if not isinstance(node, Mapping):
            raise ValueError(f"Le contexte de {code} n'est pas un dictionnaire imbriqué.")
        if part not in node:
            return ABSENT
        node = node[part]
    return node


def inserer_contexte(context, code, value):
    node = context
    parts = code.split(".")
    for part in parts[:-1]:
        if part in node and not isinstance(node[part], dict):
            raise ValueError(f"Collision dans le contexte pour {code}.")
        node = node.setdefault(part, {})
    if parts[-1] in node:
        raise ValueError(f"Collision dans le contexte pour {code}.")
    node[parts[-1]] = None if value is ABSENT else value


class GenerationContextValidator:
    def validate(self, balises, context, manual_values=None):
        """Valide exclusivement les définitions de balises sélectionnées.

        context : dictionnaire imbriqué produit par DocumentContextBuilder.
        manual_values : valeurs instructeur indexées par code complet, par exemple
        {"quantite_prelevement": 0}. L'absence d'une clé diffère d'une saisie vide.
        missing liste les saisies obligatoires restant à demander ; errors contient
        les configurations ou saisies rejetées. Une valeur connue présente ne peut
        pas être remplacée par une saisie. Aucun contrôle de type n'est ajouté ici.
        """
        if not isinstance(context, Mapping) or (manual_values is not None and not isinstance(manual_values, Mapping)):
            raise TypeError("context et manual_values doivent être des dictionnaires.")
        manual_values = {} if manual_values is None else manual_values
        balises = list(balises)
        result = {"resolved": {}, "missing": [], "errors": []}

        def erreur(code, message):
            result["errors"].append({"code": code, "message": message})

        def demander(balise, reason):
            result["missing"].append({
                "code": balise.code, "libelle": balise.libelle, "type": balise.type,
                "required": balise.required, "allow_blank": not balise.required,
                "help_text": balise.help_text, "reason": reason,
            })

        selected = {balise.code for balise in balises}
        for code in sorted(set(manual_values) - selected):
            erreur(code, "Cette balise ne fait pas partie de la sélection.")
        seen = set()
        for balise in balises:
            code = balise.code
            if code in seen:
                erreur(code, "Balise présente plusieurs fois dans la sélection.")
                continue
            seen.add(code)
            if not balise.actif or balise.mode not in Balise.Mode.values:
                erreur(code, "Balise inactive ou mode inconnu.")
                continue
            try:
                known = lire_contexte(context, code) if balise.mode == Balise.Mode.CONNUE else ABSENT
            except ValueError as exc:
                erreur(code, str(exc))
                continue
            supplied = code in manual_values
            if balise.mode == Balise.Mode.CONNUE and not valeur_vide(known):
                if supplied:
                    erreur(code, "Une valeur connue présente ne peut pas être remplacée.")
                    continue
                value = known
            elif supplied:
                value = manual_values[code]
                if valeur_vide(value) and balise.required:
                    erreur(code, "Une valeur explicitement saisie ne peut pas être vide.")
                    if balise.required:
                        demander(balise, "valeur_vide_interdite")
                    continue
            elif balise.mode == Balise.Mode.CONNUE:
                if balise.required:
                    demander(balise, "connue_vide")
                    continue
                value = known
            else:
                if balise.required:
                    demander(balise, "saisie_requise")
                    continue
                value = [] if balise.type == Balise.Type.LIST else ABSENT
            if isinstance(value, str):
                value = value.strip()
            try:
                inserer_contexte(result["resolved"], code, value)
            except ValueError as exc:
                erreur(code, str(exc))
        return result
