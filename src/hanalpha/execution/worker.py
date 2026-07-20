from __future__ import annotations

from datetime import datetime

from hanalpha.execution.control_models import ExecutionLease
from hanalpha.execution.control_store import DurableExecutionStore
from hanalpha.execution.fake_broker import BrokerSubmissionUnknown, DurableFakeBroker


class ExecutionWorker:
    def __init__(
        self,
        store: DurableExecutionStore,
        broker: DurableFakeBroker,
        lease: ExecutionLease,
    ) -> None:
        self.store = store
        self.broker = broker
        self.lease = lease
        self.broker.advance_fence(lease.fencing_token)

    def dispatch_once(self, *, at: datetime) -> bool:
        self.store.record_heartbeat(
            "execution-worker",
            status="OK",
            at=at,
            details={"fencing_token": self.lease.fencing_token},
        )
        claimed = self.store.claim_next(self.lease, at=at)
        if claimed is None:
            return False
        command, intent = claimed
        try:
            self.store.validate_lease(self.lease, at=at)
            events = self.broker.submit(intent, fencing_token=self.lease.fencing_token, at=at)
        except BrokerSubmissionUnknown as exc:
            self.store.mark_submission_unknown(command.command_id, at=at, reason=str(exc))
            return True
        for event in events:
            self.store.ingest_broker_event(event)
        self.store.mark_delivered(command.command_id, at=at)
        return True

    def dispatch_cancel_once(self, *, at: datetime) -> bool:
        self.store.record_heartbeat(
            "execution-worker",
            status="OK",
            at=at,
            details={"fencing_token": self.lease.fencing_token},
        )
        claimed = self.store.claim_next_cancel(self.lease, at=at)
        if claimed is None:
            return False
        command_id, intent = claimed
        try:
            self.store.validate_lease(self.lease, at=at)
            events = self.broker.cancel(
                intent.client_order_key, fencing_token=self.lease.fencing_token, at=at
            )
        except BrokerSubmissionUnknown as exc:
            self.store.mark_cancel_unknown(command_id, at=at, reason=str(exc))
            return True
        for event in events:
            self.store.ingest_broker_event(event)
        self.store.mark_cancel_delivered(command_id, at=at)
        return True
