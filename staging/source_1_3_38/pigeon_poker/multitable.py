from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
import uuid



def next_big_blind_index_after_rotation(dealer_index: int, seat_count: int = 6) -> int:
    """Return the BB seat for the next full-ring hand after a one-seat button move.

    Rush & Cash refills the five opponent seats before every hand, so all seats
    are considered occupied. The next button moves one seat clockwise; the BB
    is two seats left of that next button.
    """
    count = int(seat_count)
    if count < 2:
        raise ValueError("seat_count must be at least 2")
    next_button = (int(dealer_index) + 1) % count
    return (next_button + 2) % count


@dataclass
class CashTableSlot:
    table_id: str
    rate: str
    state: dict[str, Any]
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))


class MultiTableRegistry:
    """Small in-memory registry for independently stateful Rush & Cash tables.

    Wallet balance and persistent stores intentionally remain outside each slot,
    so every table shares one account while keeping its own hand/CPU/session state.
    """

    def __init__(self, max_tables: int = 2):
        if max_tables < 1:
            raise ValueError("max_tables must be at least one")
        self.max_tables = int(max_tables)
        self._slots: dict[str, CashTableSlot] = {}
        self.active_id: str | None = None

    def add(self, rate: str, state: dict[str, Any], table_id: str | None = None) -> CashTableSlot:
        if len(self._slots) >= self.max_tables:
            raise RuntimeError(f"Maximum of {self.max_tables} simultaneous tables reached")
        identifier = table_id or uuid.uuid4().hex[:8]
        if identifier in self._slots:
            raise ValueError(f"Duplicate table id: {identifier}")
        slot = CashTableSlot(identifier, str(rate), dict(state))
        self._slots[identifier] = slot
        self.active_id = identifier
        return slot

    def update_active(self, state: dict[str, Any], rate: str | None = None) -> None:
        slot = self.get_active()
        if slot is None:
            return
        slot.state = dict(state)
        if rate is not None:
            slot.rate = str(rate)

    def activate(self, table_id: str) -> CashTableSlot:
        if table_id not in self._slots:
            raise KeyError(f"Unknown table: {table_id}")
        self.active_id = table_id
        return self._slots[table_id]

    def remove(self, table_id: str) -> CashTableSlot:
        if table_id not in self._slots:
            raise KeyError(f"Unknown table: {table_id}")
        removed = self._slots.pop(table_id)
        if self.active_id == table_id:
            self.active_id = next(reversed(self._slots), None)
        return removed

    def get_active(self) -> CashTableSlot | None:
        return self._slots.get(self.active_id) if self.active_id else None

    def get(self, table_id: str) -> CashTableSlot | None:
        return self._slots.get(table_id)

    def list(self) -> list[CashTableSlot]:
        return list(self._slots.values())

    def __len__(self) -> int:
        return len(self._slots)

    @property
    def full(self) -> bool:
        return len(self._slots) >= self.max_tables
