"""Construction de contextes imbriqués, sans écrasement silencieux."""

from copy import deepcopy
import re


def set_nested_value(context, code, value):
    if not re.fullmatch(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*", code):
        raise ValueError(f"Code de balise invalide : {code}.")
    node = context
    parts = code.split(".")
    for part in parts[:-1]:
        if part in node and not isinstance(node[part], dict):
            raise ValueError(f"Collision dans le contexte pour {code}.")
        node = node.setdefault(part, {})
    if parts[-1] in node:
        raise ValueError(f"Valeur déjà définie pour {code}.")
    node[parts[-1]] = value


def merge_contexts(known, manual):
    """Complète uniquement les valeurs absentes ou vides ; préserve 0 et False."""
    from .validation import valeur_vide

    result = deepcopy(known)

    def merge(target, source, prefix=""):
        for key, value in source.items():
            code = f"{prefix}.{key}" if prefix else key
            if key not in target:
                target[key] = deepcopy(value)
            elif isinstance(target[key], dict) and isinstance(value, dict):
                merge(target[key], value, code)
            elif isinstance(value, dict) or isinstance(target[key], dict):
                raise ValueError(f"Collision dans le contexte pour {code}.")
            elif valeur_vide(target[key]):
                target[key] = deepcopy(value)
            else:
                raise ValueError(f"Une valeur connue présente ne peut pas être remplacée : {code}.")
    merge(result, manual)
    return result
