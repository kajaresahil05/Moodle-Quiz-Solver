"""
tests/test_code_quality.py
Automated static analysis test.
Verifies that NO Python file in the codebase has undefined variables,
missing imports, or syntax errors.
"""
import ast
import glob
import os
import pyflakes.checker
import pyflakes.messages


def test_no_syntax_errors_or_undefined_names():
    """
    Scans every Python file across app/, tests/, and root.
    Fails immediately if any file has a syntax error or references
    an undefined name (such as a missing import like 'import re').
    """
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    py_files = (
        glob.glob(os.path.join(root_dir, "app", "**", "*.py"), recursive=True)
        + glob.glob(os.path.join(root_dir, "tests", "**", "*.py"), recursive=True)
        + glob.glob(os.path.join(root_dir, "*.py"))
    )

    # Filter out virtual environment files if any exist in the directory
    py_files = [f for f in py_files if "venv" not in f and ".venv" not in f]

    assert len(py_files) > 0, "No python files found to test"

    errors = []

    for filepath in py_files:
        rel_path = os.path.relpath(filepath, root_dir)
        with open(filepath, "rb") as fp:
            source = fp.read()

        try:
            tree = ast.parse(source, filename=rel_path)
        except SyntaxError as e:
            errors.append(f"SyntaxError in {rel_path}:{e.lineno}: {e.msg}")
            continue

        checker = pyflakes.checker.Checker(tree, filename=rel_path)
        for msg in checker.messages:
            if isinstance(msg, pyflakes.messages.UndefinedName):
                errors.append(
                    f"UndefinedName in {rel_path}:{msg.lineno}: '{msg.message_args[0]}' is not defined / not imported"
                )

    assert not errors, "Code quality check failed with undefined symbols/syntax errors:\n" + "\n".join(errors)
