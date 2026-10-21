import ast
from pathlib import Path

import custom_components.guestbook.core as core


def test_core_modules_import_nothing_from_home_assistant():
    for path in Path(core.__file__).parent.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
            if isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            assert not any(n.split(".")[0] == "homeassistant" for n in names), path.name
