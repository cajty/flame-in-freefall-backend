from __future__ import annotations

from pathlib import Path

from core.data.loader import CsvRepository
from core.data.registry import FileSpec, InvestigationAdapter, Pick
from core.data.summary import summarize_investigation


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_loader_preserves_quotes_blanks_and_bom(tmp_path: Path):
    _write(
        tmp_path / "a.csv",
        '﻿date , fuel , o2\r\n2020-01-01,"ethane, propane",21\r\n2020-02-01, methane ,\r\n',
    )
    repo = CsvRepository(tmp_path)
    frame = repo.load("a.csv").frame

    assert list(frame.columns)[:3] == ["row_index", "source_file", "date"]
    assert list(frame["date"].tolist()) == ["2020-01-01", "2020-02-01"]
    assert frame.loc[0, "fuel"] == "ethane, propane"
    assert frame.loc[1, "fuel"] == "methane"
    assert frame.loc[1, "o2"] == ""
    assert frame.loc[0, "row_index"] == 0
    assert frame.loc[1, "row_index"] == 1
    assert frame.loc[0, "source_file"] == "a.csv"


def test_loader_cache_returns_same_frame(tmp_path: Path):
    _write(tmp_path / "a.csv", "x\n1\n")
    repo = CsvRepository(tmp_path)
    first = repo.load("a.csv")
    second = repo.load("a.csv")
    assert first is second


def test_summary_treats_blank_values_as_missing_not_zero(tmp_path: Path):
    _write(
        tmp_path / "a.csv",
        "date,fuel,o2\n2020-01-01,fuel-a,21\n2020-01-02,fuel-b,\n",
    )
    adapter = InvestigationAdapter(
        id="fixture",
        files=(
            FileSpec(
                "a.csv",
                Pick(date="date", o2=(("o2", 1.0),), fuel="fuel"),
            ),
        ),
        variables=("fuel", "o2"),
    )
    repo = CsvRepository(tmp_path)
    summary = summarize_investigation(repo, adapter)

    assert summary.tests == 2
    assert summary.date is not None
    assert summary.date.start == "2020-01-01"
    assert summary.o2 is not None
    assert (summary.o2.min, summary.o2.max) == (21.0, 21.0)
    assert summary.fuels == ["fuel-a", "fuel-b"]


def test_loader_rejects_path_outside_data_dir(tmp_path: Path):
    repo = CsvRepository(tmp_path)
    try:
        repo.load("../outside.csv")
    except ValueError as error:
        assert "outside data directory" in str(error)
    else:
        raise AssertionError("expected ValueError")
