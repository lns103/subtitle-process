"""事件发射：统一补齐 ``event_id`` / ``seq`` / ``ts``。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .models import Event, utc_now


class EventEmitter:
    """每个 run 一个实例，保证 ``seq`` 单调递增。"""

    def __init__(
        self,
        send: Callable[[Event], None],
        *,
        run_id: str | None = None,
        project_id: str | None = None,
    ) -> None:
        self._send = send
        self._run_id = run_id
        self._project_id = project_id
        self._seq = 0

    @property
    def seq(self) -> int:
        return self._seq

    def emit(self, event_type: str, **fields: Any) -> Event:
        self._seq += 1
        event = Event(
            event_id=f"evt_{self._seq:06d}",
            run_id=fields.pop("run_id", self._run_id),
            project_id=fields.pop("project_id", self._project_id),
            seq=self._seq,
            type=event_type,
            ts=utc_now(),
            **fields,
        )
        self._send(event)
        return event
