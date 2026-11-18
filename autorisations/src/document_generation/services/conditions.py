"""Conditions de visibilité issues de l'AST Jinja, sans exécution de code fourni."""
from jinja2 import nodes
from .analyzer import _path


def expression(node):
    path = _path(node)
    if path:
        return ['value', path]
    if isinstance(node, nodes.Const) and isinstance(node.value, (str, int, float, bool, type(None))):
        return ['const', node.value]
    if isinstance(node, (nodes.And, nodes.Or)):
        return ['and' if isinstance(node, nodes.And) else 'or', expression(node.left), expression(node.right)]
    if isinstance(node, nodes.Not):
        return ['not', expression(node.node)]
    if isinstance(node, nodes.Compare) and all(op.op in ('eq', 'ne', 'gt', 'gteq', 'lt', 'lteq') for op in node.ops):
        return ['compare', expression(node.expr), [[op.op, expression(op.expr)] for op in node.ops]]
    raise ValueError('Condition non prise en charge')


def collect_conditions(trees, codes, types=None):
    occurrences = {code: [] for code in codes}
    warnings = set()

    def visit(node, guards):
        if isinstance(node, nodes.If):
            previous = []
            for branch in [node, *node.elif_]:
                visit(branch.test, guards + previous)
                try:
                    test = expression(branch.test)
                    def references(rule):
                        if isinstance(rule, list):
                            if rule and rule[0] == 'value':
                                yield rule[1]
                            else:
                                for part in rule:
                                    yield from references(part)
                    if any(code not in occurrences for code in references(test)):
                        raise ValueError('Variable locale de boucle')
                    if any((types or {}).get(code) in ('DATE', 'LIST') for code in references(test)) and any(
                            isinstance(item, nodes.Compare) for item in [branch.test, *branch.test.find_all(nodes.Compare)]):
                        raise ValueError('Comparaison de valeurs complexes')
                except ValueError:
                    warnings.add('Une condition complexe ne peut pas piloter le formulaire ; ses champs restent visibles.')
                    for child in branch.body:
                        visit(child, guards)
                    # Toutes les autres branches restent accessibles par prudence.
                    previous = []
                    continue
                for child in branch.body:
                    visit(child, guards + previous + [test])
                previous.append(['not', test])
            for child in node.else_:
                visit(child, guards + previous)
            return
        path = _path(node)
        if path in occurrences:
            occurrences[path].append(['and', *guards])
            return
        for child in node.iter_child_nodes():
            visit(child, guards)

    for tree in trees:
        visit(tree, [])
    return {code: ['or', *paths] for code, paths in occurrences.items()}, sorted(warnings)


def evaluate(rule, values):
    op, *args = rule
    if op == 'value':
        return values.get(args[0])
    if op == 'const':
        return args[0]
    if op == 'and':
        return all(evaluate(arg, values) for arg in args)
    if op == 'or':
        return any(evaluate(arg, values) for arg in args)
    if op == 'not':
        return not evaluate(args[0], values)
    if op == 'compare':
        left = evaluate(args[0], values)
        for kind, right_rule in args[1]:
            right = evaluate(right_rule, values)
            try:
                result = {'eq': lambda: left == right, 'ne': lambda: left != right,
                          'gt': lambda: left > right, 'gteq': lambda: left >= right,
                          'lt': lambda: left < right, 'lteq': lambda: left <= right}[kind]()
            except TypeError:
                result = False
            if not result:
                return False
            left = right
        return True
    return True


def active(balise, values):
    rule = getattr(balise, 'visibility_rule', None)
    return rule is None or bool(evaluate(rule, values))
