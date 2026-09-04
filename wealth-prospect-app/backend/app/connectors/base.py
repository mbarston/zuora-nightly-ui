"""
Connector contract.

A connector turns a prospect identity (name, address, employer…) into a list
of SignalDrafts. Each connector declares its provenance metadata so the UI
can show users *where* every fact came from, on what legal basis, and what
it costs — the transparency WealthEngine-style black boxes lack.

`mode` is one of:
  - "live"     : calls the real upstream API (requires LIVE_CONNECTORS=true)
  - "synthetic": returns deterministic fake signals (default; offline/dev)
  - "planned"  : metadata only, no implementation yet
"""
from __future__ import annotations

import abc
from dataclasses import dataclass, field

from app.scoring.signals import SignalDraft


@dataclass
class ProspectIdentity:
    id: int | None
    first_name: str
    last_name: str
    email: str | None = None
    street: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    employer: str | None = None
    title: str | None = None
    age_band: str | None = None

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


@dataclass
class ConnectorMeta:
    key: str
    name: str
    category: str
    description: str
    legal_basis: str
    cost: str
    coverage: str
    refresh: str
    signal_kinds: list[str] = field(default_factory=list)
    docs_url: str | None = None


class Connector(abc.ABC):
    meta: ConnectorMeta
    supports_live: bool = False

    @abc.abstractmethod
    def fetch_synthetic(self, p: ProspectIdentity) -> list[SignalDraft]: ...

    def fetch_live(self, p: ProspectIdentity) -> list[SignalDraft]:  # pragma: no cover - network
        raise NotImplementedError

    def fetch(self, p: ProspectIdentity, live: bool) -> list[SignalDraft]:
        if live and self.supports_live:
            return self.fetch_live(p)
        return self.fetch_synthetic(p)

    @property
    def mode(self) -> str:
        from app.config import settings

        if settings.LIVE_CONNECTORS and self.supports_live:
            return "live"
        return "synthetic"
