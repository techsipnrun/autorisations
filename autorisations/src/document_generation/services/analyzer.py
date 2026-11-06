"""Analyse en lecture seule : aucun rendu, aucune sauvegarde ni synchronisation SQL."""

from dataclasses import asdict, dataclass, field
from io import BytesIO
from django.core.exceptions import ValidationError
from docxtpl import DocxTemplate
from jinja2 import Environment, TemplateError, nodes

from autorisations.models.models_generation import Balise
from .providers import KNOWN_PROVIDERS
from .template_path import read_template_bytes, TemplatePathError


@dataclass
class AnalysisReport:
    balises: list = field(default_factory=list)
    erreurs: list = field(default_factory=list)
    syntaxe_valide: bool = False
    analyse_complete: bool = False

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

    def parse(self, *args, **kwargs):
        tree = super().parse(*args, **kwargs)
        self.trees.append(tree)
        return tree


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
        report = self.analyze_bytes(data)
        if any(entry['code'] == 'document.numero' for entry in report.balises):
            from .numbers import number_kind
            if not number_kind(template):
                report.erreurs.append('document.numero nécessite une nature de template avec numérotation (acte ou Avis instance).')
        return data, report

    def analyze_bytes(self, data, catalogue=None):
        """Analyse un DOCX en mémoire ; catalogue injectable pour les tests isolés."""
        report = AnalysisReport()
        env = AnalysisEnvironment()
        try:
            tpl = DocxTemplate(BytesIO(data))
            roots = tpl.get_undeclared_template_variables(jinja_env=env)
        except TemplateError as exc:
            report.erreurs.append(f"Erreur Jinja/docxtpl : {exc}")
            return report
        except Exception as exc:
            report.erreurs.append(f"DOCX inexploitable : {type(exc).__name__}.")
            return report

        codes, errors = set(), set()
        report.syntaxe_valide = True
        for tree in env.trees:
            _collect(tree, roots, codes, errors)
        report.erreurs.extend(sorted(errors))
        report.analyse_complete = not errors
        if catalogue is None:
            catalogue = Balise.objects.filter(code__in=codes).prefetch_related("sources_champs__id_champ")
        by_code = {balise.code: balise for balise in catalogue}
        for code in sorted(codes):
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
        return report
