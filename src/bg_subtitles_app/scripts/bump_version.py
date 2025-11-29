#!/usr/bin/env python3
import re
import sys
from pathlib import Path


def replace_in_file(path: Path, pattern: re.Pattern, repl_func):
    text = path.read_text(encoding="utf-8")
    new_text = pattern.sub(repl_func, text)
    if new_text != text:
        path.write_text(new_text, encoding="utf-8")


def main():
    if len(sys.argv) != 2:
        print("usage: bump_version.py X.Y.Z", file=sys.stderr)
        sys.exit(2)
    version = sys.argv[1]
    if not re.match(r"^[0-9]+\.[0-9]+\.[0-9]+$", version):
        print("error: version must be X.Y.Z", file=sys.stderr)
        sys.exit(2)

    # Update src/app.py MANIFEST["version"]
    app_py = Path("src/app.py")
    manifest_re = re.compile(r"(\"version\"\s*:\s*\")[^"]+(\")")

    def repl_manifest(m):
        return f'{m.group(1)}{version}{m.group(2)}'

    replace_in_file(app_py, manifest_re, repl_manifest)

    # Update README badge version-<x.y.z>
    readme = Path("README.md")
    badge_re = re.compile(r"(version-)[0-9]+\.[0-9]+\.[0-9]+(-blue)\)")

    def repl_badge(m):
        return f"{m.group(1)}{version}{m.group(2)})"

    replace_in_file(readme, badge_re, repl_badge)

    print(f"Bumped version to {version}")


if __name__ == "__main__":
    main()

