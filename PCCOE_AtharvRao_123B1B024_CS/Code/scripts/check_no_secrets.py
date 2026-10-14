"""Fail when tracked files contain credentials, environment files or archives.

A committed ``peoject.zip`` once carried a real ``backend/.env`` (provider keys and a database
password) into the remote repository. This guard scans every tracked file - and the *inside* of tracked
zip archives - so that cannot happen silently again.

Run:  python scripts/check_no_secrets.py                 # tracked files of this repository
      python scripts/check_no_secrets.py --path <folder>  # any folder (e.g. a submission package)
      python scripts/check_no_secrets.py --zip <archive>  # the inside of an archive
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = re.compile(r"(^|/)\.env($|\.(?!example$))")
SECRET_PATTERNS = {
    "Google API key": re.compile(r"AIza[0-9A-Za-z_\-]{35}"),
    "Groq API key": re.compile(r"gsk_[0-9A-Za-z]{30,}"),
    "OpenAI-style key": re.compile(r"sk-[0-9A-Za-z]{32,}"),
    "private key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "database URL with password": re.compile(
        r"postgres(?:ql)?(?:\+\w+)?://[^:@/\s]+:(?!development-only-change-me|unavailable)[^@/\s<$]{4,}@"
    ),
}
IGNORED_DIRECTORIES = ("node_modules/", ".git/")


def tracked_files() -> list[str]:
    output = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    return [
        line
        for line in output.splitlines()
        if line and not line.startswith(IGNORED_DIRECTORIES)
    ]


def scan_text(label: str, text: str, problems: list[str]) -> None:
    for name, pattern in SECRET_PATTERNS.items():
        if pattern.search(text):
            problems.append(f"{label}: looks like a {name}")


def scan_archive(label: str, path: Path, problems: list[str]) -> None:
    """Scan every member of a zip archive (names and text content)."""
    try:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                if ENV_FILE.search(member):
                    problems.append(
                        f"{label}!{member}: environment file inside archive"
                    )
                    continue
                if (
                    member.endswith("/")
                    or archive.getinfo(member).file_size > 2_000_000
                ):
                    continue
                try:
                    scan_text(
                        f"{label}!{member}",
                        archive.read(member).decode("utf-8"),
                        problems,
                    )
                except UnicodeDecodeError:
                    continue
    except zipfile.BadZipFile:
        problems.append(f"{label}: not a readable zip archive")


def scan_folder(folder: Path, problems: list[str]) -> int:
    count = 0
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or "node_modules" in path.parts or ".git" in path.parts:
            continue
        name = path.relative_to(folder).as_posix()
        count += 1
        if ENV_FILE.search(name):
            problems.append(f"{name}: environment files must not be shipped")
        elif name.lower().endswith(".zip"):
            scan_archive(name, path, problems)
        elif path.stat().st_size <= 2_000_000:
            try:
                scan_text(name, path.read_text(encoding="utf-8"), problems)
            except (UnicodeDecodeError, OSError):
                continue
    return count


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--path", type=Path, help="scan this folder instead of the tracked files"
    )
    parser.add_argument("--zip", type=Path, help="scan the inside of this archive")
    args = parser.parse_args()
    problems: list[str] = []
    if args.path or args.zip:
        scanned = 0
        if args.path:
            scanned += scan_folder(args.path, problems)
        if args.zip:
            scan_archive(args.zip.name, args.zip, problems)
            scanned += 1
        if problems:
            print("Potential secrets or forbidden files found:")
            for problem in problems:
                print(f"  - {problem}")
            return 1
        print(f"No secrets found in {scanned} scanned file(s).")
        return 0
    for name in tracked_files():
        path = ROOT / name
        if ENV_FILE.search(name):
            problems.append(f"{name}: environment files must not be tracked")
            continue
        if not path.is_file():
            continue
        if name.lower().endswith(".zip"):
            problems.append(
                f"{name}: archives must not be tracked (they hide their contents)"
            )
            try:
                with zipfile.ZipFile(path) as archive:
                    for member in archive.namelist():
                        if ENV_FILE.search(member):
                            problems.append(
                                f"{name}!{member}: environment file inside archive"
                            )
            except zipfile.BadZipFile:
                pass
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            scan_text(name, path.read_text(encoding="utf-8"), problems)
        except (UnicodeDecodeError, OSError):
            continue
    if problems:
        print("Potential secrets or forbidden files found:")
        for problem in problems:
            print(f"  - {problem}")
        return 1
    print("No secrets or forbidden archives found in tracked files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
