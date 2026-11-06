"""Préparation en lecture seule d'un dossier et des balises d'un seul template."""

from autorisations.models.models_generation import Balise
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
        catalogue = {b.code: b for b in Balise.objects.filter(code__in=codes).prefetch_related("sources_champs__id_champ")}
        if set(codes) != set(catalogue):
            result["errors"].append("Le catalogue a changé pendant la préparation. Rechargez la page.")
            return result
        balises = [catalogue[code] for code in codes]
        known = DocumentContextBuilder().build(dossier, [b.code for b in balises if b.mode == Balise.Mode.CONNUE], balises=balises)
        validation = GenerationContextValidator().validate(balises, known)
        missing_codes = {entry["code"] for entry in validation["missing"]}
        form_balises = [b for b in balises if b.code != 'document.numero' and (b.code in missing_codes or b.mode == Balise.Mode.A_RENSEIGNER)]
        rows = []
        for b in balises:
            if b.mode == Balise.Mode.CONNUE and b.code not in missing_codes:
                value = lire_contexte(validation["resolved"], b.code)
                if value is ABSENT:
                    continue
                display = "—" if value is None or value == "" else ("Oui" if value is True else "Non" if value is False else value)
                rows.append({"code": b.code, "libelle": b.libelle or b.code, "value": display})
        result.update(balises=balises, known_context=known, validation=validation,
                      known_rows=rows, form_balises=form_balises,
                      errors=[error["message"] for error in validation["errors"]])
        return result
