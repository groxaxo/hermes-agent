from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Protocol


@dataclass(frozen=True)
class ConnectorAction:
    """Stable action envelope exposed by an AAIT connector."""

    name: str
    arguments: Mapping[str, Any]


class Connector(Protocol):
    """Vendor-neutral connector contract owned by AAIT.

    Implementations may wrap Gmail, Google Calendar, Drive, MissedCallZero,
    ServiceM8, Xero, or another service.  Agent engines receive only the
    mediated connector capability rather than raw provider credentials.
    """

    name: str

    def capabilities(self) -> tuple[str, ...]: ...

    def invoke(self, action: ConnectorAction) -> Mapping[str, Any]: ...
