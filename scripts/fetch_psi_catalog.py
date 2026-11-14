"""Fetch NASA PSI investigation metadata into a local search catalog.

The catalog is an offline artifact. The API never calls psi.nasa.gov at
request time; it reads `data/reference/psi_catalog.json` written here.

Raw responses are cached under `data/raw/psi-catalog/` so a rerun resumes
without repeating requests. Reuse a cached record unless `--force` is given.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT_PATH = ROOT / "data" / "reference" / "psi_catalog.json"
RAW_DIR = ROOT / "data" / "raw" / "psi-catalog"
PSI_ROOT = "https://psi.nasa.gov"
STUDIES_URL = f"{PSI_ROOT}/geode-py/ws/studies"
RECORD_URL = PSI_ROOT + "/geode-py/ws/repo/investigations/{psi_id}"
USER_AGENT = "flame-atlas-catalog-fetch/1.0 (NASA PSI; local research tool)"
TIMEOUT_SECONDS = 120.0
RETRIES = 3
MAX_FIELD_CHARS = 8_000
PSI_ID_RE = re.compile(r"^PSI-\d+$")

TEXT_FIELDS = {
    "title": "title",
    "acronym": "investigationAcronym",
    "researchArea": "researchArea",
    "subResearchArea": "subResearchArea",
    "projectType": "projectType",
    "flightProgram": "flightProgram",
    "experimentHardware": "experimentHardware",
    "objective": "objective",
    "approach": "approach",
    "hypothesis": "hypothesis",
    "researchImpacts": "researchImpacts",
    "modifiedDate": "modifiedDate",
}


def _text(record: dict[str, Any], source: str) -> str:
    value = record.get(source)
    if not isinstance(value, str):
        return ""
    printable = "".join(
        character for character in value if character.isprintable() or character in "\n\t"
    )
    return " ".join(printable.split())[:MAX_FIELD_CHARS]


def extract_entry(psi_id: str, record: dict[str, Any], source_hash: str) -> dict[str, Any]:
    """Reduce a full PSI record to the fields the catalog needs.

    The full record embeds hundreds of file entries; keeping them would make
    the index tens of megabytes and add no search value.
    """
    if record.get("accession") != psi_id:
        raise ValueError(
            f"{psi_id}: record accession {record.get('accession')!r} does not match"
        )
    entry: dict[str, Any] = {"psiId": psi_id}
    for target, source in TEXT_FIELDS.items():
        entry[target] = _text(record, source)
    entry["restricted"] = record.get("restricted") is True
    entry["sourceHash"] = source_hash
    return entry


def _get_json(client: httpx.Client, url: str) -> tuple[dict[str, Any], str]:
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ValueError(f"{url} did not return a JSON object")
            return payload, hashlib.sha256(response.content).hexdigest()
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
            if attempt < RETRIES:
                time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after {RETRIES} attempts: {last_error}")


def parse_study_ids(payload: dict[str, Any]) -> list[str]:
    content = payload.get("content")
    if not isinstance(content, list):
        raise TypeError("studies endpoint did not return a content list")
    ids: list[str] = []
    for item in content:
        if not isinstance(item, str) or not PSI_ID_RE.match(item):
            raise ValueError(f"invalid PSI ID in studies response: {item!r}")
        ids.append(item)
    if not ids:
        raise ValueError("studies endpoint returned no PSI IDs")
    return sorted(set(ids), key=lambda value: int(value.removeprefix("PSI-")))


def _study_ids(client: httpx.Client) -> list[str]:
    payload, _ = _get_json(client, STUDIES_URL)
    return parse_study_ids(payload)


def _load_cached(psi_id: str) -> tuple[dict[str, Any], str] | None:
    path = RAW_DIR / f"{psi_id}.json"
    if not path.exists():
        return None
    try:
        raw = path.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    return payload, hashlib.sha256(raw).hexdigest()


def _write_cache(psi_id: str, raw_content: bytes) -> tuple[dict[str, Any], str]:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{psi_id}.json"
    path.write_bytes(raw_content)
    payload = json.loads(raw_content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"{psi_id}: cached payload is not a JSON object")
    return payload, hashlib.sha256(raw_content).hexdigest()


def _fetch_record(
    client: httpx.Client, psi_id: str
) -> tuple[dict[str, Any], str]:
    url = RECORD_URL.format(psi_id=psi_id)
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        try:
            response = client.get(url)
            response.raise_for_status()
            return _write_cache(psi_id, response.content)
        except (httpx.HTTPError, ValueError) as error:
            last_error = error
            if attempt < RETRIES:
                time.sleep(2**attempt)
    raise RuntimeError(f"GET {url} failed after {RETRIES} attempts: {last_error}")


def _existing_items() -> dict[str, dict[str, Any]]:
    """Entries from the previous index, used when a refetch fails."""
    if not OUT_PATH.exists():
        return {}
    try:
        raw = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = raw.get("items") if isinstance(raw, dict) else None
    if not isinstance(items, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if (
            isinstance(item, dict)
            and isinstance(item.get("psiId"), str)
            and PSI_ID_RE.match(item["psiId"])
        ):
            result[item["psiId"]] = item
    return result


def _write_index(items: list[dict[str, Any]]) -> None:
    if not items:
        raise ValueError("refusing to write an empty PSI catalog")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generatedAt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": STUDIES_URL,
        "count": len(items),
        "items": items,
    }
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    handle, temp_name = tempfile.mkstemp(
        prefix=".psi_catalog.", suffix=".json", dir=OUT_PATH.parent
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
        os.replace(temp_name, OUT_PATH)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="refetch cached records")
    parser.add_argument(
        "--delay", type=float, default=1.0, help="seconds between record requests"
    )
    args = parser.parse_args()

    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        timeout=TIMEOUT_SECONDS,
        follow_redirects=True,
    ) as client:
        study_ids = _study_ids(client)
        print(f"{len(study_ids)} studies listed")

        items: list[dict[str, Any]] = []
        failures: list[str] = []
        failed_ids: list[str] = []
        for position, psi_id in enumerate(study_ids, start=1):
            cached = None if args.force else _load_cached(psi_id)
            try:
                if cached is None:
                    record, source_hash = _fetch_record(client, psi_id)
                    time.sleep(args.delay)
                else:
                    record, source_hash = cached
                items.append(extract_entry(psi_id, record, source_hash))
                print(f"[{position}/{len(study_ids)}] {psi_id} ok")
            except Exception as error:
                failed_ids.append(psi_id)
                failures.append(f"{psi_id}: {error}")
                print(f"[{position}/{len(study_ids)}] {psi_id} FAILED: {error}")

    previous = _existing_items()
    merged = dict(previous)
    for item in items:
        merged[item["psiId"]] = item
    items = sorted(merged.values(), key=lambda item: int(item["psiId"].removeprefix("PSI-")))
    if not items:
        print("no records fetched and no previous catalog; not writing the index")
        return 1
    _write_index(items)
    print(f"wrote {OUT_PATH} with {len(items)} records")
    kept = [psi_id for psi_id in failed_ids if psi_id in previous]
    if kept:
        print(f"kept previous entries for: {', '.join(kept)}")
    if failures:
        print("failed records:")
        for failure in failures:
            print(f"  {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
