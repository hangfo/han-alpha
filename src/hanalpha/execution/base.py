from __future__ import annotations

from typing import Protocol

from hanalpha.domain.models import AccountSnapshot, OrderEvent, OrderRequest, Quote
from hanalpha.runtime.capabilities import BrokerWriteCapability


class Broker(Protocol):
    async def is_connected(self) -> bool: ...

    async def get_account_snapshot(self) -> AccountSnapshot: ...

    async def submit(
        self,
        order: OrderRequest,
        quote: Quote,
        capability: BrokerWriteCapability | None,
    ) -> list[OrderEvent]: ...

    async def process_quote(self, quote: Quote) -> list[OrderEvent]: ...

    async def cancel_all(
        self, capability: BrokerWriteCapability | None
    ) -> list[OrderEvent]: ...

    async def flatten_all(
        self,
        quotes: dict[str, Quote],
        capability: BrokerWriteCapability | None,
    ) -> list[OrderEvent]: ...
