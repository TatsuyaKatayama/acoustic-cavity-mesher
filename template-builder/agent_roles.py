"""Load repository-owned role instructions and their declared shared skills."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
B3_ROLES = {'coordinator': 'coordinator', 'worker': 'b3-worker',
            'checker': 'b3-checker', 'strategy': 'b3-strategy'}


def load_role(role):
    if role not in {*B3_ROLES.values(), 'b4-checker'}:
        raise ValueError(f'Unknown workflow role: {role}')
    definition = (ROOT / 'agents' / role / 'AGENT.md').read_text(encoding='utf-8')
    sections = [definition.strip()]
    for line in definition.splitlines():
        if line.startswith('Skill:'):
            name = line.removeprefix('Skill:').strip()
            if not re.fullmatch(r'[a-z0-9-]+', name):
                raise ValueError(f'Invalid skill name for {role}: {name}')
            skill = (ROOT / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')
            sections.append(skill.strip())
    return '\n\n'.join(sections)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=(*B3_ROLES.values(), 'b4-checker'))
    args = parser.parse_args()
    print(load_role(args.role))
