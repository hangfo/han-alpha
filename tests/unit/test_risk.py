from datetime import timedelta

from hanalpha.risk import RiskEngine


def test_position_size_is_bounded(signal, account, regime, quote, risk_config) -> None:
    engine = RiskEngine(risk_config.risk)
    quantity = engine.size_position(signal=signal, account=account, regime=regime, quote=quote)
    assert quantity > 0
    assert quantity * quote.ask <= account.net_liquidation * risk_config.risk.max_symbol_weight


def test_stale_quote_is_rejected(plan, account, regime, quote, risk_config, now) -> None:
    stale = quote.model_copy(update={"timestamp": now - timedelta(minutes=5)})
    engine = RiskEngine(risk_config.risk)
    decision = engine.evaluate(
        plan=plan,
        account=account,
        quote=stale,
        regime=regime,
        existing_idempotency_keys=set(),
        average_dollar_volume=100_000_000,
        now=now,
    )
    assert not decision.approved
    assert "stale_quote" in decision.reason_codes


def test_duplicate_is_rejected(plan, account, regime, quote, risk_config, now) -> None:
    engine = RiskEngine(risk_config.risk)
    decision = engine.evaluate(
        plan=plan,
        account=account,
        quote=quote,
        regime=regime,
        existing_idempotency_keys={plan.idempotency_key},
        average_dollar_volume=100_000_000,
        now=now,
    )
    assert not decision.approved
    assert "duplicate_idempotency_key" in decision.reason_codes


def test_kill_switch_rejects(plan, account, regime, quote, risk_config, now) -> None:
    engine = RiskEngine(risk_config.risk)
    engine.kill_switch.freeze("operator")
    decision = engine.evaluate(
        plan=plan,
        account=account,
        quote=quote,
        regime=regime,
        existing_idempotency_keys=set(),
        average_dollar_volume=100_000_000,
        now=now,
    )
    assert not decision.approved
    assert "kill_switch_frozen" in decision.reason_codes


def test_existing_symbol_position_is_rejected(plan, account, regime, quote, risk_config, now) -> None:
    from hanalpha.domain.models import Position

    occupied = account.model_copy(
        update={
            "positions": [
                Position(symbol="NVDA", quantity=10, average_cost=90, mark_price=100)
            ]
        }
    )
    engine = RiskEngine(risk_config.risk)
    decision = engine.evaluate(
        plan=plan,
        account=occupied,
        quote=quote,
        regime=regime,
        existing_idempotency_keys=set(),
        average_dollar_volume=100_000_000,
        now=now,
    )
    assert not decision.approved
    assert "existing_symbol_position" in decision.reason_codes
