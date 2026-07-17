from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime
from itertools import combinations

from pydantic import BaseModel, ConfigDict

from hanalpha.pit.calendar import ExchangeCalendar, MarketPhase
from hanalpha.pit.models import (
    CanonicalRecord,
    InstrumentRecord,
    PriceBarRecord,
    SymbolAliasRecord,
)
from hanalpha.pit.symbology import interval_contains, intervals_overlap


class QualityIssue(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    message: str
    record_ids: list[str]


class QualityReport(BaseModel):
    model_config = ConfigDict(frozen=True)
    passed: bool
    issues: list[QualityIssue]
    record_count: int
    digest: str


class DataQualityGate:
    def evaluate(self, records: list[CanonicalRecord]) -> QualityReport:
        issues: list[QualityIssue] = []
        instruments = {
            record.instrument_id: record
            for record in records
            if isinstance(record, InstrumentRecord)
        }
        instrument_ids = {
            record.instrument_id for record in records if isinstance(record, InstrumentRecord)
        }
        for record in records:
            if not isinstance(record, InstrumentRecord) and record.instrument_id not in instrument_ids:
                issues.append(
                    QualityIssue(
                        code="orphan_instrument_reference",
                        message=f"{record.record_type} references unknown instrument",
                        record_ids=[record.record_id],
                    )
                )

        calendar = ExchangeCalendar()
        for record in records:
            instrument = instruments.get(record.instrument_id)
            if (
                isinstance(record, PriceBarRecord)
                and instrument is not None
                and instrument.exchange == "XNYS"
                and calendar.phase(record.event_time) != MarketPhase.RTH
            ):
                issues.append(
                    QualityIssue(
                        code="event_outside_exchange_session",
                        message="XNYS price bar event_time is outside regular trading hours",
                        record_ids=[record.record_id],
                    )
                )

        identities: dict[tuple[str, str, int], CanonicalRecord] = {}
        record_ids: dict[str, CanonicalRecord] = {}
        for record in records:
            key = (record.source, record.source_record_id, record.source_revision)
            prior = identities.get(key)
            if prior is not None and prior.payload_hash != record.payload_hash:
                issues.append(
                    QualityIssue(
                        code="conflicting_source_revision",
                        message="one source revision has multiple payload hashes",
                        record_ids=sorted([prior.record_id, record.record_id]),
                    )
                )
            identities[key] = record
            prior_id = record_ids.get(record.record_id)
            if prior_id is not None and prior_id.payload_hash != record.payload_hash:
                issues.append(
                    QualityIssue(
                        code="conflicting_record_id",
                        message="one canonical record_id has multiple payload hashes",
                        record_ids=[record.record_id],
                    )
                )
            record_ids[record.record_id] = record

        aliases: dict[str, list[SymbolAliasRecord]] = defaultdict(list)
        for record in records:
            if isinstance(record, SymbolAliasRecord):
                aliases[record.ticker.upper()].append(record)
        for ticker, group in aliases.items():
            for left, right in combinations(group, 2):
                same_logical_alias = (
                    left.source == right.source
                    and left.source_record_id == right.source_record_id
                )
                if not same_logical_alias and intervals_overlap(
                    left.valid_from, left.valid_to, right.valid_from, right.valid_to
                ):
                    issues.append(
                        QualityIssue(
                            code="overlapping_ticker_interval",
                            message=f"ticker {ticker} has overlapping validity intervals",
                            record_ids=sorted([left.record_id, right.record_id]),
                        )
                    )

        snapshot_ids = {record.snapshot_id for record in records}
        if len(snapshot_ids) > 1:
            issues.append(
                QualityIssue(
                    code="mixed_snapshot_ids",
                    message="canonical batch contains multiple snapshot ids",
                    record_ids=sorted(record.record_id for record in records),
                )
            )
        issues.sort(key=lambda item: (item.code, item.record_ids))
        digest_source = "\n".join(
            f"{item.code}|{','.join(item.record_ids)}|{item.message}" for item in issues
        ) + f"\nrecords={len(records)}"
        digest = hashlib.sha256(digest_source.encode()).hexdigest()
        return QualityReport(
            passed=not issues,
            issues=issues,
            record_count=len(records),
            digest=digest,
        )


def intervals_contain(start: datetime, end: datetime | None, point: datetime) -> bool:
    return interval_contains(start, end, point)
