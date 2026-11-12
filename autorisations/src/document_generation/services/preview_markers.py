"""Repères visuels des interpolations simples, exclusivement dans l’aperçu."""
from copy import deepcopy
from io import BytesIO
import re
from uuid import uuid4
from zipfile import ZipFile

from docxtpl import DocxTemplate
from lxml import etree
from jinja2 import Environment, nodes


W = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
TEXT = re.compile(r'(<w:t(?:\s[^>]*)?>)(.*?)(</w:t>)', re.S)
VARIABLE = re.compile(r'{{\s*([a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)*)\s*}}')
BLOCK = re.compile(r'{%-?\s*(if|for|elif|else|endif|endfor)\b(.*?)\s*-?%}', re.S)


def _paths(node):
    if isinstance(node, nodes.Name):
        return [node.name]
    if isinstance(node, nodes.Getattr):
        return [f'{path}.{node.attr}' for path in _paths(node.node)]
    if isinstance(node, nodes.Getitem) and isinstance(node.arg, nodes.Const) and isinstance(node.arg.value, str):
        return [f'{path}.{node.arg.value}' for path in _paths(node.node)]
    return [path for child in node.iter_child_nodes() for path in _paths(child)]


def _marker_at(xml, position, marker):
    """Respecter l’emplacement Word : texte, paragraphe ou ligne de tableau."""
    stack = []
    for tag in re.finditer(r'<(/?)(w:[\w]+)\b[^>]*?(/?)>', xml[:position]):
        closing, name, empty = tag.groups()
        if closing:
            if name in stack:
                stack = stack[:len(stack) - 1 - stack[::-1].index(name)]
        elif not empty:
            stack.append(name)
    parent = stack[-1] if stack else 'w:body'
    if parent == 'w:t':
        return marker
    marker = f'<w:t>{marker}</w:t>'
    if parent == 'w:r':
        return marker
    marker = f'<w:r>{marker}</w:r>'
    if parent in ('w:p', 'w:hyperlink'):
        return marker
    marker = f'<w:p>{marker}</w:p>'
    if parent == 'w:tr':
        return f'<w:tc>{marker}</w:tc>'
    if parent == 'w:tbl':
        return f'<w:tr><w:tc>{marker}</w:tc></w:tr>'
    return marker


class MarkedPreviewTemplate(DocxTemplate):
    def __init__(self, source, missing):
        super().__init__(source)
        prefix = 'AGIDA_PREVIEW_' + uuid4().hex
        self.markers = {item['code']: f'{prefix}_{index}_END' for index, item in enumerate(missing)}
        self.labels = {self.markers[item['code']]: (item['label'], '') for item in missing}
        self.missing = {item['code']: item['label'] for item in missing}

    def mark_blocks(self, xml):
        roots, stack = [], []
        for token in BLOCK.finditer(xml):
            kind = token[1]
            if kind in ('if', 'for'):
                block = {'token': token, 'children': [], 'tests': [token]}
                (stack[-1]['children'] if stack else roots).append(block)
                stack.append(block)
            elif kind == 'elif' and stack:
                stack[-1]['tests'].append(token)
            elif kind in ('endif', 'endfor') and stack:
                block = stack.pop()
                block['end'] = token.end()

        env = Environment()

        def edits(block, local):
            token = block['token']
            if 'end' not in block:
                return []  # Le moteur habituel signalera la syntaxe invalide.
            paths, aliases = [], set()
            if token[1] == 'for':
                loop = env.parse('{% for ' + token[2] + ' %}{% endfor %}').body[0]
                paths.extend(_paths(loop.iter))
                aliases = {name.name for name in loop.target.find_all(nodes.Name)}
                if isinstance(loop.target, nodes.Name):
                    aliases.add(loop.target.name)
                if loop.test is not None:
                    paths.extend(path for path in _paths(loop.test) if path.split('.')[0] not in aliases)
            else:
                for test in block['tests']:
                    condition = env.parse('{% if ' + test[2] + ' %}{% endif %}').body[0]
                    paths.extend(_paths(condition.test))
            required = [code for code in self.missing if any(
                path.split('.')[0] not in local and
                (code == path or code.startswith(path + '.') or path.startswith(code + '.')) for path in paths)]
            if required:
                label = ', '.join(self.missing[code] for code in required)
                suffix = ' à renseigner pour afficher du contenu' if token[1] == 'if' else ' à renseigner'
                marker = 'AGIDA_PREVIEW_BLOCK_' + uuid4().hex
                self.labels[marker] = (label, suffix)
                return [(token.start(), block['end'], _marker_at(xml, token.start(), marker))]
            return [edit for child in block['children'] for edit in edits(child, local | aliases)]

        changes = [change for block in roots for change in edits(block, set())]
        for start, end, value in sorted(changes, reverse=True):
            xml = xml[:start] + value + xml[end:]
        return xml

    def patch_xml(self, src_xml):
        xml = self.mark_blocks(super().patch_xml(src_xml))
        # Ne pas confondre une variable locale de boucle avec une balise globale.
        aliases = set()
        for target in re.findall(r'{%\s*for\s+(.+?)\s+in\s', xml):
            aliases.update(re.findall(r'[a-z][a-z0-9_]*', target))

        def mark_text(match):
            def replace(variable):
                code = variable[1]
                return self.markers.get(code, variable[0]) if code.split('.')[0] not in aliases else variable[0]
            return match[1] + VARIABLE.sub(replace, match[2]) + match[3]
        # Seulement le texte affiché : ni conditions, ni expressions, ni attributs.
        return TEXT.sub(mark_text, xml)


def color_preview_markers(buffer, labels):
    """Sépare les runs pour colorer le repère sans recolorer le texte voisin."""
    result = BytesIO()
    pattern = re.compile('(' + '|'.join(re.escape(token) for token in labels) + ')')
    with ZipFile(buffer) as source, ZipFile(result, 'w') as output:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename.startswith('word/') and info.filename.endswith('.xml') and any(token.encode() in data for token in labels):
                root = etree.fromstring(data, etree.XMLParser(resolve_entities=False, no_network=True))
                for run in list(root.iter(W + 'r')):
                    if not any(pattern.search(text.text or '') for text in run.findall(W + 't')):
                        continue
                    properties = run.find(W + 'rPr')

                    def new_run(marker=False, bold=False):
                        element = etree.Element(W + 'r', dict(run.attrib))
                        if properties is not None:
                            element.append(deepcopy(properties))
                        if marker:
                            style = element.find(W + 'rPr')
                            if style is None:
                                style = etree.SubElement(element, W + 'rPr')
                            for tag, attributes in [('color', {'val': 'B42318'}), ('shd', {'val': 'clear', 'fill': 'FDECEC'})]:
                                for old in style.findall(W + tag):
                                    style.remove(old)
                                etree.SubElement(style, W + tag, {W + key: value for key, value in attributes.items()})
                            for tag in ('b', 'bCs'):
                                for old in style.findall(W + tag):
                                    style.remove(old)
                                etree.SubElement(style, W + tag, {W + 'val': '1' if bold else '0'})
                        return element

                    pieces, current = [], new_run()
                    for child in run:
                        if child.tag == W + 'rPr':
                            continue
                        if child.tag != W + 't' or not pattern.search(child.text or ''):
                            current.append(deepcopy(child))
                            continue
                        for text in pattern.split(child.text or ''):
                            if not text:
                                continue
                            if text in labels:
                                pieces.append(current)
                                label, instruction = labels[text]
                                for part, bold in (('[', False), (label, True), (instruction + ']', False)):
                                    marked = new_run(marker=True, bold=bold)
                                    node = etree.SubElement(marked, W + 't')
                                    node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                                    node.text = part
                                    pieces.append(marked)
                                current = new_run()
                            else:
                                node = etree.SubElement(current, W + 't')
                                node.set('{http://www.w3.org/XML/1998/namespace}space', 'preserve')
                                node.text = text
                    pieces.append(current)
                    parent, index = run.getparent(), run.getparent().index(run)
                    for element in pieces:
                        if any(child.tag != W + 'rPr' for child in element):
                            parent.insert(index, element)
                            index += 1
                    parent.remove(run)
                data = etree.tostring(root, encoding='UTF-8', xml_declaration=True, standalone=True)
            output.writestr(info, data)
    result.seek(0)
    return result
