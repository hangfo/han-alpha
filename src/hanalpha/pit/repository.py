from __future__ import annotations

from hanalpha.pit.canonical_store import CanonicalStore
from hanalpha.pit.catalog import PITCatalog
from hanalpha.pit.context import AsOfContext
from hanalpha.pit.models import (
    CorporateActionRecord,
    InstrumentRecord,
    PriceBarRecord,
    SymbolAliasRecord,
)


class SnapshotNotPublished(RuntimeError):
    """A query attempted to cross the staged/published boundary."""


class AsOfRepository:
    """The only supported strategy-facing entry point into PIT data."""

    def __init__(self, catalog: PITCatalog, store: CanonicalStore) -> None:
        self._catalog = catalog
        self._store = store

    def resolve_ticker(self, ticker: str, context: AsOfContext) -> SymbolAliasRecord | None:
        payloads = self._query(
            context,
            "record_type = 'symbol_alias' AND upper(json_extract_string(payload_json, '$.ticker')) = ?",
            [ticker.upper()],
        )
        aliases = [SymbolAliasRecord.model_validate(payload) for payload in payloads]
        if len(aliases) > 1:
            raise RuntimeError(f"ambiguous ticker at as_of: {ticker}")
        return aliases[0] if aliases else None

    def active_instruments(self, context: AsOfContext) -> list[InstrumentRecord]:
        return [
            InstrumentRecord.model_validate(payload)
            for payload in self._query(context, "record_type = 'instrument'", [])
        ]

    def price_bars(
        self, instrument_id: str, context: AsOfContext, interval: str | None = None
    ) -> list[PriceBarRecord]:
        predicate = "record_type = 'price_bar' AND instrument_id = ?"
        parameters: list[object] = [instrument_id]
        if interval is not None:
            predicate += " AND json_extract_string(payload_json, '$.interval') = ?"
            parameters.append(interval)
        return [
            PriceBarRecord.model_validate(payload)
            for payload in self._query(context, predicate, parameters)
        ]

    def corporate_actions(
        self, instrument_id: str, context: AsOfContext
    ) -> list[CorporateActionRecord]:
        return [
            CorporateActionRecord.model_validate(payload)
            for payload in self._query(
                context,
                "record_type = 'corporate_action' AND instrument_id = ?",
                [instrument_id],
            )
        ]

    def _query(
        self, context: AsOfContext, record_predicate: str, parameters: list[object]
    ) -> list[dict[str, object]]:
        if not self._catalog.is_published(context.snapshot_id):
            raise SnapshotNotPublished(context.snapshot_id)
        temporal = (
            "available_at <= ? AND valid_from <= ? "
            "AND (valid_to IS NULL OR ? < valid_to) AND "
        )
        return self._store.query_payloads(
            context.snapshot_id,
            temporal + record_predicate,
            [context.as_of, context.as_of, context.as_of, *parameters],
        )
