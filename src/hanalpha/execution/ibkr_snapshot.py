from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Protocol

from hanalpha.domain.enums import Side
from hanalpha.execution.control_models import (
    BrokerEvent,
    BrokerEventType,
    BrokerOrderTruth,
    BrokerProtectionTruth,
    BrokerSnapshot,
)
from hanalpha.execution.ibkr_observer import (
    IBKRReadModel,
    SnapshotCompletenessCertificate,
    account_hash,
)
from hanalpha.simulation.events import canonical_hash


class ClientKeyResolver(Protocol):
    def resolve_client_order_prefix(self, prefix: str) -> str | None: ...


class IBKRBrokerSnapshotAdapter:
    """Account-scoped conversion from raw IBKR read state to the M5 reconciliation contract."""

    @classmethod
    def build(
        cls,
        read_model: IBKRReadModel,
        certificate: SnapshotCompletenessCertificate,
        *,
        configured_account: str,
        key_resolver: ClientKeyResolver | None = None,
    ) -> BrokerSnapshot:
        expected_account = account_hash(configured_account)
        if certificate.visibility.configured_account_hash != expected_account:
            raise ValueError("certificate account scope does not match configured account")
        account_values = {
            (str(payload.get("tag")), str(payload.get("currency"))): Decimal(
                str(payload.get("value", "0"))
            )
            for payload in read_model.account_values.values()
            if payload.get("account_hash") == expected_account
        }
        base_currency = certificate.base_currency
        if not base_currency or not certificate.base_currency_seen:
            raise ValueError("broker base currency is not authoritative")
        cash = cls._account_value(account_values, "TotalCashValue", base_currency)
        by_numeric_id: dict[tuple[int, int], str] = {}
        key_by_identity: dict[str, str] = {}
        for identity, payload in read_model.orders.items():
            if payload.get("account_hash") != expected_account:
                continue
            client_key = cls._client_key(identity, payload, key_resolver)
            key_by_identity[identity] = client_key
            by_numeric_id[(int(payload.get("client_id", 0)), int(payload["order_id"]))] = client_key
        broker_orders: list[BrokerOrderTruth] = []
        protection_orders: list[BrokerProtectionTruth] = []
        symbol_protections: dict[str, int] = {}
        for identity, payload in read_model.orders.items():
            if identity not in key_by_identity:
                continue
            parent_id = int(payload.get("parent_id", 0) or 0)
            quantity = cls._int_quantity(payload.get("quantity", 0))
            filled = cls._int_quantity(payload.get("filled", 0))
            side = cls._side(payload.get("action", "BUY"))
            client_key = key_by_identity[identity]
            if parent_id == 0:
                broker_orders.append(
                    BrokerOrderTruth(
                        broker_order_id=identity,
                        client_order_key=client_key,
                        instrument_id=str(payload.get("symbol") or payload.get("con_id")),
                        side=side,
                        quantity=quantity,
                        filled_quantity=filled,
                        status=str(payload.get("status", "UNKNOWN")),
                        perm_id=(
                            str(payload["perm_id"]) if int(payload.get("perm_id", 0) or 0) else None
                        ),
                    )
                )
                continue
            parent_key = by_numeric_id.get((int(payload.get("client_id", 0)), parent_id))
            if parent_key is None:
                parent_key = canonical_hash(
                    {
                        "session": read_model.session_id,
                        "client_id": int(payload.get("client_id", 0)),
                        "parent_order_id": parent_id,
                    }
                )
            order_type = str(payload.get("order_type", "")).upper()
            if order_type in {"STP", "STP LMT"}:
                protection_type = "STOP"
            elif order_type == "LMT":
                protection_type = "TARGET"
            else:
                raise ValueError(f"unsupported broker child order type: {order_type or 'EMPTY'}")
            active = str(payload.get("status", "")).lower() not in {
                "cancelled",
                "apicancelled",
                "filled",
                "inactive",
            }
            protection_orders.append(
                BrokerProtectionTruth(
                    protection_order_id=identity,
                    parent_client_order_key=parent_key,
                    protection_type=protection_type,
                    quantity=quantity,
                    active=active,
                )
            )
            if active and protection_type == "STOP":
                symbol = str(payload.get("symbol") or payload.get("con_id"))
                symbol_protections[symbol] = symbol_protections.get(symbol, 0) + quantity
        events = cls._events(
            read_model,
            expected_account=expected_account,
            key_by_identity=key_by_identity,
            key_resolver=key_resolver,
            as_of=certificate.as_of,
        )
        positions = {
            str(payload.get("symbol") or payload.get("con_id")): cls._signed_quantity(
                payload.get("position", 0)
            )
            for payload in read_model.positions.values()
            if payload.get("account_hash") == expected_account
            and cls._signed_quantity(payload.get("position", 0)) != 0
        }
        currency_balances = {
            currency: value
            for (tag, currency), value in account_values.items()
            if tag == "TotalCashValue" and currency not in {"BASE", ""}
        }
        return BrokerSnapshot(
            as_of=certificate.as_of,
            cash=cash,
            settled_cash=cls._optional_account_value(account_values, "SettledCash", base_currency),
            buying_power=cls._optional_account_value(account_values, "BuyingPower", base_currency),
            accrued_cash=cls._optional_account_value(account_values, "AccruedCash", base_currency),
            base_currency=base_currency,
            currency_balances=currency_balances or {base_currency: cash},
            complete=certificate.complete,
            completeness_certificate_id=certificate.certificate_id,
            observation_id=certificate.certificate_id,
            session_id=certificate.session_id,
            final_watermark=certificate.final_watermark,
            semantic_hash=certificate.semantic_hash,
            visibility_scope_hash=certificate.visibility.scope_hash,
            account_hash=certificate.account_hash,
            orders_hash=certificate.orders_hash,
            positions_hash=certificate.positions_hash,
            executions_hash=certificate.executions_hash,
            commissions_hash=certificate.commissions_hash,
            protection_hash=certificate.protection_hash,
            valuation_hash=certificate.valuation_hash,
            normalization_policy_hash=certificate.normalization_policy_hash,
            valuation_fields={
                key: Decimal(value) for key, value in certificate.valuation_fields.items()
            },
            order_snapshot_complete=certificate.order_snapshot_complete,
            position_snapshot_complete=certificate.position_snapshot_complete,
            execution_snapshot_complete=certificate.execution_snapshot_complete,
            cash_snapshot_complete=certificate.cash_snapshot_complete,
            commission_pending_count=certificate.executions_missing_commission_count,
            orders=tuple(sorted(broker_orders, key=lambda item: item.broker_order_id)),
            positions=positions,
            protections=symbol_protections,
            events=events,
            protection_orders=tuple(
                sorted(protection_orders, key=lambda item: item.protection_order_id)
            ),
        )

    @classmethod
    def _events(
        cls,
        model: IBKRReadModel,
        *,
        expected_account: str,
        key_by_identity: dict[str, str],
        key_resolver: ClientKeyResolver | None,
        as_of: datetime,
    ) -> tuple[BrokerEvent, ...]:
        order_lookup = {
            (int(payload.get("client_id", 0)), int(payload["order_id"])): key
            for identity, payload in model.orders.items()
            if (key := key_by_identity.get(identity)) is not None
        }
        events: list[BrokerEvent] = []
        for sequence, (root, execution) in enumerate(
            sorted(model.effective_executions.items()), start=1
        ):
            if execution.get("account_hash") != expected_account:
                continue
            exec_id = str(execution["exec_id"])
            order_ref = str(execution.get("order_ref", ""))
            client_key = cls._key_from_ref(order_ref, key_resolver) or order_lookup.get(
                (
                    int(execution.get("client_id", 0)),
                    int(execution.get("order_id", 0)),
                )
            )
            if client_key is None:
                client_key = canonical_hash({"session": model.session_id, "execution_root": root})
            commission = model.effective_commissions.get(root, {})
            quantity = cls._int_quantity(execution.get("shares", 0))
            received_at = cls._received_at(execution, as_of)
            occurred_at, parse_status, broker_timezone = cls._broker_time(
                execution.get("time"), received_at
            )
            raw = {
                "execution": execution,
                "commission": commission,
                "broker_time_parse_status": parse_status,
                "broker_timezone": broker_timezone,
                "clock_skew_ms": max(0, int((received_at - occurred_at).total_seconds() * 1000)),
            }
            events.append(
                BrokerEvent(
                    broker_event_id=canonical_hash({"ibkr_exec_id": exec_id, "raw": raw}),
                    broker_order_id=str(execution.get("perm_id") or execution.get("order_id")),
                    client_order_key=client_key,
                    event_type=BrokerEventType.FILL,
                    sequence=sequence,
                    filled_quantity=quantity,
                    fill_price=Decimal(str(execution.get("price", "0"))),
                    commission=Decimal(str(commission.get("commission", "0") or "0")),
                    occurred_at=occurred_at,
                    received_at=received_at,
                    raw_payload_hash=canonical_hash(raw),
                )
            )
        return tuple(events)

    @staticmethod
    def _key_from_ref(order_ref: str, resolver: ClientKeyResolver | None) -> str | None:
        if not order_ref.startswith("HA:"):
            return None
        encoded = order_ref.removeprefix("HA:")
        prefix, separator, leg = encoded.rpartition(":")
        if not (separator and leg in {"P", "T", "S"}):
            prefix = encoded
        if len(prefix) == 64:
            return prefix
        return resolver.resolve_client_order_prefix(prefix) if resolver else None

    @classmethod
    def _client_key(
        cls,
        identity: str,
        payload: dict[str, Any],
        resolver: ClientKeyResolver | None,
    ) -> str:
        return cls._key_from_ref(str(payload.get("order_ref", "")), resolver) or canonical_hash(
            {"broker_order_identity": identity}
        )

    @classmethod
    def _account_value(
        cls, values: dict[tuple[str, str], Decimal], tag: str, currency: str
    ) -> Decimal:
        result = cls._optional_account_value(values, tag, currency)
        if result is None:
            raise ValueError(f"required account value is missing: {tag}")
        return result

    @staticmethod
    def _optional_account_value(
        values: dict[tuple[str, str], Decimal], tag: str, currency: str
    ) -> Decimal | None:
        return values.get((tag, currency), values.get((tag, "BASE")))

    @staticmethod
    def _int_quantity(value: Any) -> int:
        return max(0, int(Decimal(str(value or "0"))))

    @staticmethod
    def _signed_quantity(value: Any) -> int:
        return int(Decimal(str(value or "0")))

    @staticmethod
    def _side(value: Any) -> Side:
        return Side.BUY if str(value).upper() in {"BUY", "BOT"} else Side.SELL

    @staticmethod
    def _received_at(payload: dict[str, Any], fallback: datetime) -> datetime:
        raw = payload.get("_received_at")
        return datetime.fromisoformat(str(raw)) if raw else fallback

    @staticmethod
    def _broker_time(value: Any, fallback: datetime) -> tuple[datetime, str, str | None]:
        raw = str(value or "").strip()
        if not raw:
            return fallback, "MISSING_FALLBACK_RECEIVED_AT", None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is not None:
                return parsed.astimezone(UTC), "PARSED_OFFSET", str(parsed.tzinfo)
        except ValueError:
            pass
        if raw.endswith(" UTC"):
            try:
                parsed = datetime.strptime(raw, "%Y%m%d %H:%M:%S UTC").replace(tzinfo=UTC)
                return parsed, "PARSED_UTC", "UTC"
            except ValueError:
                pass
        return fallback, "AMBIGUOUS_FALLBACK_RECEIVED_AT", None
