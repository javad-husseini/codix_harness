"""Bounded instruction-only Skill discovery through the existing project file policy."""
import re
from backend.policy import redact

MAX_CANDIDATES = 32
MAX_SELECTED = 3
MAX_BODY = 4000
MAX_TOTAL = 8000
STOP = {'use', 'when', 'the', 'and', 'for', 'with', 'that', 'this', 'from', 'task', 'project', 'should', 'only'}


def words(text):
    tokens = re.findall(r'[^\W\d_]+', text.casefold())
    aliases = {'تست': 'test', 'آزمون': 'test', 'بررسی': 'check', 'اصلاح': 'fix'}
    return {aliases.get(word, re.sub(r'(ing|s)$', '', word) if len(word) > 5 else word)
            for word in tokens if len(word) > 2 and word not in STOP}


def parse_skill(text):
    if not text.startswith('---\n') or '\n---\n' not in text[4:]:
        raise ValueError('Missing bounded frontmatter')
    header, body = text[4:].split('\n---\n', 1)
    metadata = {}
    for line in header.splitlines():
        key, separator, value = line.partition(':')
        if separator and key in ('name', 'description'):
            if key in metadata:
                raise ValueError('Duplicate metadata')
            value = value.strip()
            if value[:1] in ('"', "'"):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError('Invalid quoted scalar')
                value = value[1:-1]
            metadata[key] = value
    name, description = metadata.get('name', ''), metadata.get('description', '')
    if (not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,63}', name)
            or not 1 <= len(description) <= 1000 or description in ('|', '>')
            or not body.strip() or len(body) > MAX_BODY):
        raise ValueError('Invalid or oversized metadata/body')
    return {'name': name, 'description': description, 'instructions': body.strip()}


def load_skills(tools, project_id, request, root_entries):
    selected, warnings, candidates = [], [], []
    if root_entries.get('truncated'):
        warnings.append('Project root listing was truncated; Skills outside the returned entries were not discovered.')

    def read(name, **arguments):
        proposal = tools.propose(project_id, name, arguments)
        return tools.execute(project_id, proposal['ticket'])

    def listing(path):
        result = read('list_files', path=path)
        if result.get('truncated'):
            warnings.append('Skill discovery listing was truncated; omitted entries were not loaded.')
        return result['entries']

    try:
        if not any(item['name'] == '.agents' and item['directory'] for item in root_entries['entries']):
            return selected, warnings
        if not any(item['name'] == 'skills' and item['directory'] for item in listing('.agents')):
            return selected, warnings
        folders = [item for item in listing('.agents/skills') if item['directory']]
        if len(folders) > MAX_CANDIDATES:
            warnings.append('Skill candidate limit reached; remaining folders were not loaded.')
        terms = words(request)
        for folder in folders[:MAX_CANDIDATES]:
            path = f".agents/skills/{folder['name']}/SKILL.md"
            try:
                raw = read('read_file', path=path)['content'].replace('\r\n', '\n')
                skill = parse_skill(raw)
                skill['path'] = path
                explicit = skill['name'].casefold() in request.casefold()
                score = len(terms & words(skill['name'] + ' ' + skill['description']))
                if explicit or score:
                    candidates.append((1000 if explicit else score, skill))
            except (ValueError, PermissionError, RuntimeError, OSError):
                # Never publish raw project/parser errors or content from an invalid Skill.
                if folder['name'].casefold() in request.casefold() or terms & words(folder['name']):
                    warnings.append(f'Skipped relevant Skill at {redact(path)}: invalid, unreadable or blocked by file policy.')
        size = 0
        for _, skill in sorted(candidates, key=lambda item: (-item[0], item[1]['path'])):
            length = len(skill['instructions']) + len(skill['description'])
            if len(selected) >= MAX_SELECTED or size + length > MAX_TOTAL:
                warnings.append(f"Skipped relevant Skill {skill['name']}: instruction context limit reached.")
                continue
            selected.append(skill)
            size += length
    except (ValueError, PermissionError, RuntimeError, OSError):
        warnings.append('Project Skill discovery was blocked or unavailable; no external path or executable Skill was used.')
    return selected, warnings
