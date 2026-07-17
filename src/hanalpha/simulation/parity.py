from __future__ import annotations

from hanalpha.simulation.events import DecisionRecord


class ParityMismatch(AssertionError):
    pass


class ParityHarness:
    """Compare deterministic decisions while intentionally ignoring adapter fills."""

    def assert_decision_parity(
        self, left: list[DecisionRecord], right: list[DecisionRecord]
    ) -> None:
        left_keys = [self._key(item) for item in left]
        right_keys = [self._key(item) for item in right]
        if left_keys != right_keys:
            raise ParityMismatch(f"decision traces differ: {left_keys!r} != {right_keys!r}")

    @staticmethod
    def _key(item: DecisionRecord) -> tuple[object, ...]:
        identity = item.identity
        return (
            identity.decision_id,
            identity.snapshot_id,
            identity.strategy_version,
            identity.config_hash,
            identity.input_hash,
            identity.signal_hash,
            identity.risk_hash,
            item.approved,
            item.reason,
        )
