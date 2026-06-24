"""Pruebas que garantizan imports sin efectos secundarios."""

import subprocess
import sys
from pathlib import Path


def test_package_imports_have_no_side_effects(tmp_path: Path) -> None:
    script = """
import importlib
import logging
import os
import pathlib
import pkgutil
import sqlite3
import sys
import urllib.request

os.chdir(sys.argv[1])

def forbidden(*args, **kwargs):
    raise AssertionError("Import attempted an external side effect")

sqlite3.connect = forbidden
urllib.request.urlopen = forbidden
root_handlers = list(logging.getLogger().handlers)
barbarion_handlers = list(logging.getLogger("barbarion").handlers)

package = importlib.import_module("barbarion")
module_names = ["barbarion"]
module_names.extend(
    module.name for module in pkgutil.walk_packages(
        package.__path__, prefix="barbarion."
    )
)
for module_name in module_names:
    importlib.import_module(module_name)

assert list(pathlib.Path.cwd().iterdir()) == []
assert list(logging.getLogger().handlers) == root_handlers
assert list(logging.getLogger("barbarion").handlers) == barbarion_handlers
"""

    result = subprocess.run(
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
