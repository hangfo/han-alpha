from hanalpha.portfolio import Ledger


def test_idempotency_persists(tmp_path) -> None:
    path = tmp_path / "ledger.sqlite3"
    ledger = Ledger(path)
    ledger.reserve_idempotency("abc", "order-1", "2026-01-01T00:00:00Z")
    assert ledger.has_idempotency_key("abc")
    ledger.close()
    reopened = Ledger(path)
    assert reopened.has_idempotency_key("abc")
    reopened.close()
