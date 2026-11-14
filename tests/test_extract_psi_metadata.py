from __future__ import annotations

import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import extract_psi_metadata  # noqa: E402


def _write_zip(path: Path, entries: dict[str, str]) -> Path:
    with zipfile.ZipFile(path, "w") as archive:
        for name, text in entries.items():
            archive.writestr(name, text)
    return path


def test_extract_zip_writes_isa_tab_files(tmp_path):
    zip_path = _write_zip(
        tmp_path / "metadata.zip",
        {"i_Investigation.txt": "INVESTIGATION\n", "s_PSI-102.txt": "STUDY\n"},
    )

    out_dir = tmp_path / "out"
    written = extract_psi_metadata.extract_zip(zip_path, out_dir)

    assert sorted(path.name for path in written) == ["i_Investigation.txt", "s_PSI-102.txt"]
    assert (out_dir / "i_Investigation.txt").read_text() == "INVESTIGATION\n"


def test_extract_zip_rejects_path_traversal(tmp_path):
    zip_path = _write_zip(tmp_path / "bad.zip", {"../evil.txt": "no"})

    with pytest.raises(ValueError, match="unsafe archive path"):
        extract_psi_metadata.extract_zip(zip_path, tmp_path / "out")

    assert not (tmp_path / "evil.txt").exists()
