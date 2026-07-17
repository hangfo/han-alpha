from __future__ import annotations

import hashlib
from datetime import datetime


def signal_id(strategy: str, symbol: str, timestamp: datetime) -> str:
    raw = f"{strategy}|{symbol}|{timestamp.isoformat()}".encode()
    return hashlib.sha256(raw).hexdigest()[:24]
