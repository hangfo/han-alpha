from __future__ import annotations

import hashlib
import html
import json
import os
import tempfile
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from hanalpha.experiments.models import (
    ArtifactDigest,
    ExperimentManifest,
    ExperimentResult,
)


class ResultBundleWriter:
    def write(
        self,
        manifest: ExperimentManifest,
        result: ExperimentResult,
        directory: Path,
    ) -> list[ArtifactDigest]:
        if result.experiment_id != manifest.experiment_id:
            raise ValueError("result does not belong to manifest")
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        payloads = {
            "cash-ledger.jsonl": self._jsonl(result.cash_entries),
            "journal.jsonl": self._jsonl(result.journal_entries),
            "manifest.json": self._json(manifest.model_dump(mode="json", exclude_none=True)),
            "position-lots.jsonl": self._jsonl(result.position_lots),
            "result.json": self._json(result.model_dump(mode="json", exclude_none=True)),
            "report.html": self._html(manifest, result).encode(),
        }
        for name, content in payloads.items():
            target = directory / name
            if target.exists() and target.read_bytes() != content:
                raise RuntimeError(f"artifact bundle is immutable: {name}")
        digests: list[ArtifactDigest] = []
        for name in sorted(payloads):
            content = payloads[name]
            target = directory / name
            if not target.exists():
                descriptor, temporary = tempfile.mkstemp(
                    prefix=f".{name}.", suffix=".tmp", dir=directory
                )
                try:
                    with os.fdopen(descriptor, "wb") as handle:
                        handle.write(content)
                        handle.flush()
                        os.fsync(handle.fileno())
                    os.replace(temporary, target)
                except BaseException:
                    Path(temporary).unlink(missing_ok=True)
                    raise
            digests.append(
                ArtifactDigest(
                    name=name,
                    sha256=hashlib.sha256(content).hexdigest(),
                    size=len(content),
                )
            )
        return digests

    @staticmethod
    def _json(payload: object) -> bytes:
        return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()

    @staticmethod
    def _jsonl(items: Sequence[BaseModel]) -> bytes:
        return b"".join(
            (
                json.dumps(
                    item.model_dump(mode="json", exclude_none=True),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            ).encode()
            for item in items
        )

    @staticmethod
    def _html(manifest: ExperimentManifest, result: ExperimentResult) -> str:
        metrics = result.metrics
        rows = [
            ("Experiment", manifest.experiment_id),
            ("Snapshot", manifest.snapshot_id),
            ("Strategy", f"{manifest.strategy_id}@{manifest.strategy_version}"),
            ("Hypothesis", manifest.hypothesis),
            ("Total return", str(metrics.total_return)),
            ("Max drawdown", str(metrics.max_drawdown)),
            ("Turnover", str(metrics.turnover)),
            ("Ending equity", str(metrics.ending_equity)),
            ("Event hash", result.event_hash),
            ("Equity hash", result.equity_hash),
        ]
        table = "".join(
            f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
            for label, value in rows
        )
        return (
            '<!doctype html><html><head><meta charset="utf-8">'
            "<title>Han Alpha Experiment</title>"
            "<style>body{font-family:system-ui;max-width:900px;margin:40px auto;}"
            "table{border-collapse:collapse;width:100%;}th,td{border:1px solid #ddd;"
            "padding:8px;text-align:left;}th{width:28%;background:#f5f5f5;}</style>"
            "</head><body><h1>Han Alpha experiment report</h1>"
            "<p>Engineering evidence only; not a profitability claim.</p>"
            f"<table>{table}</table></body></html>\n"
        )
