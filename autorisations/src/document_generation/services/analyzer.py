"""Analyse en lecture seule : aucun rendu, aucune sauvegarde ni synchronisation SQL."""

from dataclasses import asdict, dataclass, field
from io import BytesIO
import re
from html import unescape
from django.core.exceptions import ValidationError
from docxtpl import DocxTemplate
from jinja2 import Environment, TemplateError, TemplateSyntaxError, nodes

from autorisations.models.models_generation import Balise
from .providers import KNOWN_PROVIDERS
from .template_path import read_template_bytes, TemplatePathError


@dataclass
class AnalysisReport:
    balises: list = field(default_factory=list)
    erreurs: list = field(default_factory=list)
    syntaxe_valide: bool = False
    analyse_complete: bool = False
    conditions: dict = field(default_factory=dict)
    avertissements: list = field(default_factory=list)

    @property
    def valide(self):
        return not self.erreurs

    def as_dict(self):
        counts = {mode: sum(b["statut"] == mode for b in self.balises)
                  for mode in ("CONNUE", "A_RENSEIGNER", "INCONNUE")}
        return {"valide": self.valide, "total": len(self.balises), "compteurs": counts, **asdict(self)}


class AnalysisEnvironment(Environment):
    """Capture l'AST exact analysé par l'API docxtpl, après patch XML Word."""

    def __init__(self):
        super().__init__()
        self.trees = []
        self.analysis_source = ""

    def parse(self, source, *args, **kwargs):
        # Word n'a pas de lignes stables : une ligne d'analyse par paragraphe.
        # Cette copie ne sert qu'à l'analyse, jamais au rendu du document.
        self.analysis_source = re.sub(r"(<w:p(?:\s|>))", r"\n\1", source)
        tree = super().parse(self.analysis_source, *args, **kwargs)
        self.trees.append(tree)
        return tree


def _syntax_diagnostic(exc, source):
    """Explication concise accompagnée de l'extrait Word concerné."""
    message = exc.message
    expected = re.search(r"expected token '([^']+)', got '([^']+)'", message)
    if expected:
        token, found = expected.groups()
        token = {"end of print statement": "la fermeture de la balise (}})",
                 "end of statement block": "la fermeture de l’instruction (%})"}.get(token, f"« {token} »")
        reason = f"Élément inattendu : « {found} » ; élément attendu : {token}. Vérifiez l’expression : les noms de balise doivent être sans espaces (exemple : numero_acte)."
    elif "Unexpected end of template" in message:
        reason = "Une condition ou une boucle n’est pas fermée. Vérifiez les instructions {% endif %} et {% endfor %}, ainsi que leur ordre."
    elif "unknown tag" in message.lower():
        tag = re.search(r"unknown tag '([^']+)'", message, re.I)
        reason = f"Instruction inconnue ou mal placée{f' : « {tag.group(1)} »' if tag else ''}. Vérifiez son orthographe et l’imbrication des blocs if/for."
    elif "No filter named" in message:
        reason = "Un filtre utilisé dans une balise n’est pas disponible. Vérifiez le nom placé après le caractère |."
    else:
        reason = "Expression de balise incorrecte. Vérifiez les délimiteurs {{ … }} / {% … %}, les guillemets, les opérateurs et la fermeture des blocs."
    lines = source.splitlines(keepends=True)
    index = max(0, min((getattr(exc, "lineno", 1) or 1) - 1, len(lines) - 1))
    current = lines[index] if lines else ""
    excerpt = unescape(re.sub(r"<[^>]+>", "", current))
    excerpt = " ".join(excerpt.split())[:400]
    return reason + (f" Extrait concerné : « {excerpt} »." if excerpt else "")


def _path(node):
    if isinstance(node, nodes.Name):
        return node.name
    if isinstance(node, nodes.Getattr):
        parent = _path(node.node)
        return f"{parent}.{node.attr}" if parent else None
    if isinstance(node, nodes.Getitem) and isinstance(node.arg, nodes.Const) and isinstance(node.arg.value, str):
        parent = _path(node.node)
        return f"{parent}.{node.arg.value}" if parent else None
    return None


def _collect(node, roots, codes, errors):
    if isinstance(node, nodes.For):
        # Le code de la collection est une balise ; ses alias et loop restent locaux.
        if not isinstance(node.iter, (nodes.List, nodes.Tuple, nodes.Name, nodes.Getattr, nodes.Getitem)):
            errors.add("L'itérable de la boucle for n'est pas pris en charge.")
            return
        _collect(node.iter, roots, codes, errors)
        targets = {item.name for item in node.target.find_all(nodes.Name)}
        if isinstance(node.target, nodes.Name):
            targets.add(node.target.name)
        local_roots = roots - targets - {"loop"}
        if node.test is not None:
            _collect(node.test, local_roots, codes, errors)
        for child in node.body:
            _collect(child, local_roots, codes, errors)
        for child in node.else_:
            _collect(child, roots, codes, errors)
        return
    # Les macros et affectations nécessiteront une analyse
    # de portée dédiée ; on les refuse explicitement plutôt que d'omettre une balise.
    if isinstance(node, (nodes.Assign, nodes.AssignBlock, nodes.Macro,
                         nodes.Import, nodes.FromImport, nodes.Include, nodes.Extends,
                         nodes.Call, nodes.CallBlock)):
        errors.add(f"Construction Jinja non prise en charge à cette étape : {type(node).__name__}.")
        return
    if isinstance(node, (nodes.Getattr, nodes.Getitem, nodes.Name)):
        code = _path(node)
        if code and code.split(".")[0] in roots:
            try:
                Balise._meta.get_field("code").clean(code, None)
            except ValidationError:
                errors.add(f"Code de balise non conforme : {code}.")
            else:
                codes.add(code)
            return
        if isinstance(node, nodes.Getitem) and code is None:
            errors.add("Les accès dynamiques ou indexés ne sont pas pris en charge à cette étape.")
            return
    for child in node.iter_child_nodes():
        _collect(child, roots, codes, errors)


class TemplateAnalyzer:
    def analyze(self, template):
        return self.analyze_with_source(template)[1]

    def analyze_with_source(self, template):
        """Retourne le snapshot exact qui a servi à l'analyse, sans écriture."""
        try:
            data = read_template_bytes(template)
        except TemplatePathError as exc:
            return b"", AnalysisReport(erreurs=[str(exc)])
        report = self.analyze_bytes(data, template=template)
        if any(entry['code'] == 'document.numero' for entry in report.balises):
            from .numbers import number_kind
            if not number_kind(template):
                report.erreurs.append('document.numero nécessite une nature de template avec numérotation (acte ou Avis instance).')
        return data, report

    def analyze_bytes(self, data, catalogue=None, *, template=None):
        """Analyse un DOCX en mémoire ; catalogue injectable pour les tests isolés."""
        report = AnalysisReport()
        env = AnalysisEnvironment()
        try:
            tpl = DocxTemplate(BytesIO(data))
            roots = tpl.get_undeclared_template_variables(jinja_env=env)
        except TemplateSyntaxError as exc:
            report.erreurs.append(_syntax_diagnostic(exc, env.analysis_source))
            return report
        except TemplateError:
            report.erreurs.append("Le modèle contient une expression Jinja/docxtpl non prise en charge. Vérifiez les balises et les filtres utilisés.")
            return report
        except Exception as exc:
            report.erreurs.append(f"DOCX inexploitable : {type(exc).__name__}.")
            return report

        codes, errors = set(), set()
        report.syntaxe_valide = True
        for tree in env.trees:
            _collect(tree, roots, codes, errors)
        report.erreurs.extend(sorted(errors))
        from .conditions import collect_conditions
        report.analyse_complete = not errors
        if catalogue is None:
            catalogue = Balise.objects.filter(Balise.perimetre(template), code__in=codes).prefetch_related("sources_champs__id_champ")
        by_code = {balise.code: balise for balise in catalogue}
        report.conditions, report.avertissements = collect_conditions(env.trees, codes, {code: balise.type for code, balise in by_code.items()})
        for code in sorted(codes):
            first_error = len(report.erreurs)
            balise = by_code.get(code)
            statut = balise.mode if balise else "INCONNUE"
            report.balises.append({"code": code, "statut": statut})
            if balise is None:
                report.erreurs.append(f"Balise inconnue : {code}.")
            elif not balise.actif:
                report.erreurs.append(f"Balise inactive : {code}.")
            elif balise.mode == Balise.Mode.CONNUE and not balise.source and code not in KNOWN_PROVIDERS:
                report.erreurs.append(f"Balise connue sans provider : {code}.")
            elif balise.mode not in Balise.Mode.values:
                report.erreurs.append(f"Mode de balise invalide : {code}.")
            elif balise.source:
                from .catalogue_sources import source_errors
                report.erreurs.extend(f"{code} : {error}" for error in source_errors(balise))
            if balise is not None and len(report.erreurs) > first_error:
                report.balises[-1]['erreurs'] = report.erreurs[first_error:]
        return report
