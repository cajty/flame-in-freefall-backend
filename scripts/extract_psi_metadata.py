from __future__ import annotations

import argparse
import json
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "data" / "reference" / "psi_metadata_manifest.json"
RAW_DIR = ROOT / "data" / "raw" / "psi"
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_TOTAL_BYTES = 100 * 1024 * 1024


def safe_parts(name: str) -> tuple[str, ...]:
    if not name or name.startswith(("/", "\\")):
        raise ValueError(f"absolute archive path: {name}")
    if "\\" in name:
        raise ValueError(f"unsafe archive path separator: {name}")
    parts = PurePosixPath(name).parts
    if any(part in ("", ".", "..") for part in parts):
        raise ValueError(f"unsafe archive path: {name}")
    return parts


def extract_zip(zip_path: Path, out_dir: Path) -> list[Path]:
    written: list[Path] = []
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        total = sum(info.file_size for info in infos)
        if total > MAX_TOTAL_BYTES:
            raise ValueError(f"archive expands to {total} bytes, over {MAX_TOTAL_BYTES}")

        root = out_dir.resolve()
        seen: set[Path] = set()
        for info in infos:
            parts = safe_parts(info.filename)
            if info.is_dir():
                out_dir.joinpath(*parts).mkdir(parents=True, exist_ok=True)
                continue
            if stat.S_ISLNK(info.external_attr >> 16):
                raise ValueError(f"symlink in archive: {info.filename}")
            if info.file_size > MAX_FILE_BYTES:
                raise ValueError(f"archive member too large: {info.filename}")

            target = out_dir.joinpath(*parts)
            resolved = target.resolve()
            if root not in resolved.parents:
                raise ValueError(f"archive path escapes output directory: {info.filename}")
            if resolved in seen:
                raise ValueError(f"duplicate archive path: {info.filename}")
            seen.add(resolved)

            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            written.append(target)
    return written


def extract_one(record: dict, force: bool) -> tuple[str, Path, list[Path]]:
    psi_id = record["psiId"]
    zip_path = RAW_DIR / psi_id / record["fileName"]
    if not zip_path.is_file():
        raise FileNotFoundError(f"missing ZIP: {zip_path}")

    target = zip_path.parent / "extracted"
    if target.exists():
        if not force:
            return psi_id, target, sorted(path for path in target.rglob("*") if path.is_file())
        if target.parent != zip_path.parent:
            raise ValueError(f"refusing to remove unexpected directory: {target}")
        shutil.rmtree(target)

    temporary = zip_path.parent / "extracted.tmp"
    if temporary.exists():
        shutil.rmtree(temporary)
    files = extract_zip(zip_path, temporary)
    temporary.rename(target)
    return psi_id, target, files


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract downloaded PSI metadata ZIPs.")
    parser.add_argument("--force", action="store_true", help="replace existing extracted folders")
    parser.add_argument("--only", help="extract one PSI ID, for example PSI-102")
    args = parser.parse_args()

    records = json.loads(MANIFEST.read_text(encoding="utf-8"))
    selected = [item for item in records if args.only is None or item["psiId"] == args.only]
    if not selected:
        print(f"No metadata record matches --only={args.only}", file=sys.stderr)
        return 1

    failures: list[tuple[str, str]] = []
    for record in selected:
        try:
            psi_id, target, files = extract_one(record, args.force)
            print(f"{psi_id}: extracted {len(files)} file(s) to {target.relative_to(ROOT)}")
        except Exception as error:  # noqa: BLE001 - report each record and continue
            failures.append((record["psiId"], str(error)))
            print(f"{record['psiId']}: FAILED {error}", file=sys.stderr)

    if failures:
        print(f"\n{len(failures)} record(s) failed:", file=sys.stderr)
        for psi_id, message in failures:
            print(f"- {psi_id}: {message}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
