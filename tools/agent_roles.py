"""Load repository-owned role instructions and their declared shared skills."""
from pathlib import Path
import re

PROJECT = Path(__file__).resolve().parent.parent
B3_ROLES = {'coordinator': 'coordinator', 'worker': 'b3-worker',
            'checker': 'b3-checker', 'strategy': 'b3-strategy'}


def load_role(role):
    if role not in {*B3_ROLES.values(), 'b4-checker'}:
        raise ValueError(f'Unknown workflow role: {role}')
    profile = PROJECT / 'local' / 'profile'
    if not profile.is_dir():
        profile = PROJECT / 'templates' / 'profile'
    definition = (profile / 'agents' / role / 'AGENT.md').read_text(encoding='utf-8')
    sections = [definition.strip()]
    for line in definition.splitlines():
        if line.startswith('Skill:'):
            name = line.removeprefix('Skill:').strip()
            if not re.fullmatch(r'[a-z0-9-]+', name):
                raise ValueError(f'Invalid skill name for {role}: {name}')
            skill = (profile / 'skills' / name / 'SKILL.md').read_text(encoding='utf-8')
            sections.append(skill.strip())
    return '\n\n'.join(sections)

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=(*B3_ROLES.values(), 'b4-checker'))
    args = parser.parse_args()
    print(load_role(args.role))
