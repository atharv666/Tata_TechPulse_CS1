from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "package_submission.py"
spec = importlib.util.spec_from_file_location("package_submission", SCRIPT)
assert spec and spec.loader
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_secrets_caches_and_uploaded_sources_are_excluded() -> None:
    include = module.should_include
    assert include(Path("backend/app/main.py"))
    assert include(Path(".env.example"))
    assert include(Path("frontend/src/App.tsx"))
    assert not include(Path(".env"))
    assert not include(Path("backend/.env"))
    assert not include(Path("backend/.env.local"))
    assert not include(Path("backend/app/__pycache__/main.cpython-312.pyc"))
    assert not include(Path("frontend/node_modules/react/index.js"))
    assert not include(Path("frontend/dist/index.html"))
    assert not include(Path("backend/data/sources/abc.source"))
    assert not include(Path("peoject.zip"))
    assert not include(Path("PCCOE_AtharvRao_123B1B024_CS/Code/README.md"))
    assert not include(Path("texts/notes.txt"))


def test_destination_guard_protects_the_repository(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "submission/Code").mkdir(parents=True)
    unsafe = module.is_unsafe_destination
    assert unsafe(root, root)
    assert unsafe(tmp_path, root)
    assert not unsafe(root / "submission/Code", root)
    assert not unsafe(tmp_path / "elsewhere", root)
    try:
        module.copy_snapshot(root, root)
    except ValueError:
        pass
    else:  # pragma: no cover - the guard must raise before anything is deleted
        raise AssertionError("copy_snapshot accepted the repository as its destination")
    assert (root / "submission/Code").exists()


def test_snapshot_copies_only_allowed_files(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    (root / "backend/app").mkdir(parents=True)
    (root / "backend/app/main.py").write_text("print('ok')")
    (root / "backend/.env").write_text("SECRET=1")
    (root / "backend/app/cache.pyc").write_bytes(b"x")
    (root / "notes.txt").write_text("not part of the snapshot")
    destination = tmp_path / "out"
    copied = module.copy_snapshot(destination, root)
    assert copied == [Path("backend/app/main.py")]
    assert (destination / "backend/app/main.py").exists()
    assert not (destination / "backend/.env").exists()
