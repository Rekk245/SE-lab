"""Compile application modules and build a portable Python zip application."""

import compileall
import pathlib
import shutil
import tempfile
import zipapp


def main():
    """Build from current sources without bundling passwords or databases."""
    root = pathlib.Path(__file__).resolve().parents[1]
    package = root / "shared_ledger"
    if not compileall.compile_dir(package, quiet=1, force=True):
        raise SystemExit("Syntax compilation failed")
    output = root / "dist"
    output.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as temporary:
        source = pathlib.Path(temporary)
        shutil.copytree(
            package,
            source / "shared_ledger",
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        target = output / "shared_ledger.pyz"
        zipapp.create_archive(
            source, target, main="shared_ledger.__main__:main", compressed=True
        )
    print(f"Built {target.name}: {target.stat().st_size} bytes")


if __name__ == "__main__":
    main()
