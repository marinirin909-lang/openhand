#!/usr/bin/env python3
"""Check that legacy V0 API operations are marked as deprecated.

This script inspects the FastAPI app routes and verifies that any operation
implemented in a module tagged "Legacy-V0" (i.e. containing "Tag: Legacy-V0")
under openhands/server/routes/ is marked deprecated (deprecated=True).

Intended usage:
    uv run python scripts/check_legacy_v0_routes_deprecated.py

Exit codes:
    0 - All legacy V0 operations are marked deprecated
    1 - At least one legacy V0 operation is missing deprecated=True
"""

from __future__ import annotations

import importlib
from functools import lru_cache
from pathlib import Path

from fastapi.routing import APIRoute


@lru_cache(maxsize=None)
def _is_legacy_v0_routes_module(module_name: str) -> tuple[bool, Path | None]:
    module = importlib.import_module(module_name)
    module_file = getattr(module, '__file__', None)
    if not module_file:
        return False, None

    module_path = Path(module_file)

    if 'openhands/server/routes' not in module_path.as_posix():
        return False, module_path

    try:
        text = module_path.read_text(encoding='utf-8')
    except OSError:
        return False, module_path

    return 'Tag: Legacy-V0' in text, module_path


def main() -> int:
    # Importing app builds route table.
    from openhands.server.app import app

    missing: list[tuple[str, str, str, str]] = []

    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue

        if not route.path.startswith('/api/'):
            continue

        module_name = getattr(route.endpoint, '__module__', '')
        is_legacy, module_path = _is_legacy_v0_routes_module(module_name)
        if not is_legacy:
            continue

        if route.deprecated:
            continue

        methods = ','.join(
            sorted(
                m
                for m in route.methods or set()
                if m
                not in {
                    'HEAD',
                    'OPTIONS',
                }
            )
        )
        missing.append(
            (
                methods or '?',
                route.path,
                module_name,
                str(module_path) if module_path else '(unknown)',
            )
        )

    if not missing:
        print('OK: all Legacy-V0 routes under openhands/server/routes are deprecated')
        return 0

    print('ERROR: Legacy-V0 routes missing deprecated=True:\n')
    for methods, path, module_name, module_path in sorted(missing):
        print(f'- {methods:10} {path}  ({module_name} :: {module_path})')

    print(f'\nFound {len(missing)} missing deprecation marker(s).')
    return 1


if __name__ == '__main__':
    raise SystemExit(main())
