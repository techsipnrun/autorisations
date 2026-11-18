"""Préparation en lecture seule d'un dossier et des balises d'un seul template."""

from copy import copy
from autorisations.models.models_generation import Balise, TemplateBalise
from .analyzer import TemplateAnalyzer
from .context import DocumentContextBuilder
from .validation import GenerationContextValidator, lire_contexte, ABSENT


class DocumentPreparationService:
    def prepare(self, dossier, template):
        template_bytes, report = TemplateAnalyzer().analyze_with_source(template)
        result = {"balises": [], "known_context": {}, "validation": {"resolved": {}, "missing": [], "errors": []},
                  "known_rows": [], "form_balises": [], "errors": list(report.erreurs), "template_bytes": template_bytes}
        if not report.valide:
            return result
        codes = [entry["code"] for entry in report.balises]
        catalogue = {b.code: b for b in Balise.objects.filter(Balise.perimetre(template), code__in=codes).prefetch_related("sources_champs__id_champ")}
        if set(codes) != set(catalogue):
            result["errors"].append("Le catalogue a changé pendant la préparation. Rechargez la page.")
            return result
        requirements = dict(TemplateBalise.objects.filter(id_template=template).values_list('code', 'required'))
        balises = [copy(catalogue[code]) for code in codes]
        for balise in balises:
            balise.visibility_rule = report.conditions.get(balise.code)
            balise.required = balise.code == 'document.numero' or requirements.get(balise.code, False)
            balise.allow_blank = not balise.required
        known = DocumentContextBuilder().build(dossier, [b.code for b in balises if b.mode == Balise.Mode.CONNUE], balises=balises)
        validation = GenerationContextValidator().validate(balises, known)
        missing_codes = {entry["code"] for entry in validation["missing"]}
        from .validation import valeur_vide
        form_balises = [b for b in balises if b.code != 'document.numero' and
                        (b.mode == Balise.Mode.A_RENSEIGNER or
                         (b.required and valeur_vide(lire_contexte(known, b.code))))]
        rows = []
        for b in balises:
            if b.mode == Balise.Mode.CONNUE and b.code not in {item.code for item in form_balises}:
                value = lire_contexte(validation["resolved"], b.code)
                if value is ABSENT:
                    continue
                display = "—" if value is None or value == "" else ("Oui" if value is True else "Non" if value is False else value)
                rows.append({"code": b.code, "libelle": b.libelle or b.code, "value": display, 'source': b.source})
        result.update(balises=balises, known_context=known, validation=validation,
                      known_rows=rows, form_balises=form_balises,
                      errors=[error["message"] for error in validation["errors"]])
        return result
