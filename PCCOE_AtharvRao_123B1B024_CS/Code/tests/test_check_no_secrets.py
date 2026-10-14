from __future__ import annotations

import importlib.util
import zipfile
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_no_secrets.py"
spec = importlib.util.spec_from_file_location("check_no_secrets", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)

# Built at run time so this file never contains something that looks like a credential.
FAKE_GOOGLE_KEY = "AIza" + "B" * 35


def test_clean_folder_passes(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("nothing secret here")
    (tmp_path / ".env.example").write_text("GROQ_API_KEY=")
    problems: list[str] = []
    assert module.scan_folder(tmp_path, problems) == 2
    assert problems == []


def test_folder_scan_flags_env_files_keys_and_archives(tmp_path: Path) -> None:
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend/.env").write_text("X=1")
    (tmp_path / "notes.txt").write_text(f"key = {FAKE_GOOGLE_KEY}")
    with zipfile.ZipFile(tmp_path / "bundle.zip", "w") as archive:
        archive.writestr("code/.env", "SECRET=1")
        archive.writestr("code/readme.md", "fine")
    problems: list[str] = []
    module.scan_folder(tmp_path, problems)
    text = "\n".join(problems)
    assert "backend/.env: environment files must not be shipped" in text
    assert "notes.txt: looks like a Google API key" in text
    assert "bundle.zip!code/.env: environment file inside archive" in text


def test_archive_member_content_is_scanned(tmp_path: Path) -> None:
    archive_path = tmp_path / "a.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("src/config.py", f'KEY = "{FAKE_GOOGLE_KEY}"')
    problems: list[str] = []
    module.scan_archive("a.zip", archive_path, problems)
    assert problems == ["a.zip!src/config.py: looks like a Google API key"]
