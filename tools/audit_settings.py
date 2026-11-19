"""Report settings references and validate XML contracts without importing Kodi.

Literal references are evidence for manual inspection, not proof of runtime
reachability. Dynamic families below are explicitly bounded to their consumers.
The report contains IDs and locations only, never configured values or secrets.
"""
import ast
import collections
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def audit():
    definitions = list(ET.parse(ROOT / 'resources/settings.xml').iter('setting'))
    ids = [setting.get('id') for setting in definitions]
    references = collections.defaultdict(set)
    trees = {}
    for path in sorted((ROOT / 'resources/lib').glob('*.py')):
        relative = str(path.relative_to(ROOT))
        trees[relative] = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(trees[relative]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.value in ids:
                references[node.value].add(f'{relative}:{node.lineno}')

    # Only these reviewed dynamic expressions are accepted. Do not treat every
    # arbitrary variable passed to getSetting as a consumer of every setting.
    families = {
        'resources/lib/plugin.py': [
            ('menu_order_', 'f\'menu_order_{action}\''),
            ('menu_label_', "f'menu_label_{action_id}'"),
            ('menu_hide_', "f'menu_hide_{action}'"),
            ('backup_path_', "f'backup_path_{index}'"),
            ('backup_file_', "f'backup_file_{index}'"),
        ],
    }
    for path, patterns in families.items():
        nodes = list(ast.walk(trees[path]))
        for prefix, expression in patterns:
            locations = [n.lineno for n in nodes if isinstance(n, ast.JoinedStr) and ast.unparse(n) == expression]
            for setting_id in ids:
                if setting_id.startswith(prefix):
                    references[setting_id].update(f'{path}:{line} (dynamic)' for line in locations)
    tree = trees['resources/lib/recommendations.py']
    for node in ast.walk(tree):
        if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Add):
            continue
        if isinstance(node.left, ast.Name) and node.left.id == 'prefix' and isinstance(node.right, ast.Constant):
            for prefix in ('watch_movies', 'watch_series'):
                setting_id = prefix + node.right.value
                if setting_id in ids:
                    references[setting_id].add(f'resources/lib/recommendations.py:{node.lineno} (dynamic)')

    router = trees['resources/lib/plugin.py']
    routes = set()
    for function in router.body:
        if isinstance(function, ast.FunctionDef) and function.name == '_create_actions_map':
            for node in ast.walk(function):
                if isinstance(node, ast.Return) and isinstance(node.value, ast.Dict):
                    routes.update(k.value for k in node.value.keys if isinstance(k, ast.Constant))
    menu_actions = set()
    for function in router.body:
        if isinstance(function, ast.FunctionDef) and function.name == 'menu':
            for node in ast.walk(function):
                if isinstance(node, ast.Tuple) and len(node.elts) == 6 and isinstance(node.elts[1], ast.Constant):
                    menu_actions.add(node.elts[1].value)
    errors, rows = [], []
    duplicates = [key for key, count in collections.Counter(ids).items() if count > 1]
    errors.extend(f'Duplicate ID: {key}' for key in duplicates)
    catalogues = {p.parent.name: p.read_text() for p in (ROOT / 'resources/language').glob('*/strings.po')}
    for setting in definitions:
        key = setting.get('id')
        kind = 'fake' if key.startswith('FAKE') else 'action' if setting.get('type') == 'action' else 'value'
        locations = sorted(references[key])
        for prefix in ('menu_order_', 'menu_label_', 'menu_hide_'):
            if key.startswith(prefix) and key[len(prefix):] not in menu_actions:
                errors.append(f'No main menu item: {key}')
        if kind == 'action':
            data = setting.findtext('control/data') or setting.findtext('data') or ''
            match = re.search(r'[?&]action=([^&)]+)', data)
            if not match or match[1] not in routes:
                errors.append(f'Unknown action: {key}')
            else:
                locations = [f'resources/lib/plugin.py (route {match[1]})']
        elif kind != 'fake' and not locations:
            errors.append(f'No source reference: {key}')
        default = setting.findtext('default')
        options = [option.text for option in setting.findall('constraints/options/option')]
        if options and default not in options:
            errors.append(f'Default outside options: {key}')
        for condition in setting.findall('.//condition'):
            dependency = condition.get('setting')
            if dependency and dependency not in ids:
                errors.append(f'Unknown dependency: {key} -> {dependency}')
        for node in [setting, *setting.findall('.//option')]:
            for attribute in ('label', 'help'):
                ident = node.get(attribute, '')
                if ident.isdecimal():
                    for language, text in catalogues.items():
                        if f'msgctxt "#{ident}"' not in text:
                            errors.append(f'Missing {language} text: {key} #{ident}')
        rows.append({'id': key, 'type': setting.get('type'), 'kind': kind, 'references': locations})
    # Native typed getters reject a setting of another XML type.
    getter_types = {'getSettingString': {'string', 'path'},
                    'getSettingInt': {'integer'}, 'getSettingBool': {'boolean'},
                    'getSettingNumber': {'number'}}
    types = {setting.get('id'): setting.get('type') for setting in definitions}
    for path, tree in trees.items():
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in getter_types and node.args
                    and isinstance(node.args[0], ast.Constant) and node.args[0].value in types
                    and types[node.args[0].value] not in getter_types[node.func.attr]):
                errors.append(f'Wrong getter type: {node.args[0].value} {path}:{node.lineno}')
    return {'total': len(rows), 'fake': sum(r['kind'] == 'fake' for r in rows),
            'actions': sum(r['kind'] == 'action' for r in rows), 'errors': errors, 'settings': rows}


if __name__ == '__main__':
    report = audit()
    print(json.dumps(report, indent=2, ensure_ascii=False))
    raise SystemExit(bool(report['errors']))
