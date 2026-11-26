"""Serve the notices shipped with the installed viewer distributions."""

from importlib.metadata import distribution


def viewer_licenses():
    sections = []
    for name in ('ocp-viewer', 'ocp-viewer-core'):
        package = distribution(name)
        sections.append(f'{name} {package.version}'.encode())
        for entry in package.files or ():
            filename = entry.name.upper()
            if filename.startswith(('LICENSE', 'NOTICE')) or filename.startswith('THREE-CAD-VIEWER.') and (
                    'LICENSE' in filename or 'NOTICE' in filename):
                sections.extend([str(entry).encode(), entry.locate().read_bytes()])
    return b'\n\n'.join(sections)
