"""Our own presets: the providers we know, as data in ``presets.json``.

Server names, ports and hints are written from general knowledge and still
need checking against the live providers.
"""

from __future__ import annotations

from functools import cache
from importlib import resources

from pydantic import BaseModel, Field

from ..models import (
    Candidate,
    CredentialKind,
    DiscoverySourceName,
    Hint,
    MailServer,
    ProviderType,
)
from .base import Finding, Query


class CandidateTemplate(BaseModel):
    """A candidate without its source, which the lookup fills in."""

    model_config = {"extra": "forbid"}

    provider: ProviderType
    credential: CredentialKind
    oauth_provider: str | None = None
    servers: list[MailServer] = Field(default_factory=list)
    hints: list[Hint] = Field(default_factory=list)

    def build(self, name: str, source: DiscoverySourceName) -> Candidate:
        return Candidate(**self.model_dump(), name=name, source=source)


class Preset(BaseModel):
    model_config = {"extra": "forbid"}

    id: str
    name: str
    # Addresses at these domains belong to the provider.
    domains: list[str]
    # MX hosts under these registrable domains point to the provider.
    mx_domains: list[str]
    candidates: list[CandidateTemplate]
    # Notes for every address of the provider, e.g. that it offers no access.
    hints: list[Hint] = Field(default_factory=list)

    def finding(self, source: DiscoverySourceName) -> Finding:
        return Finding(
            candidates=tuple(c.build(self.name, source) for c in self.candidates),
            hints=tuple(self.hints),
        )


class _File(BaseModel):
    providers: list[Preset]


class Presets:
    def __init__(self, presets: list[Preset]) -> None:
        self.all = presets
        self._by_domain = {d: p for p in presets for d in p.domains}
        self._by_mx = {d: p for p in presets for d in p.mx_domains}

    def by_domain(self, domain: str) -> Preset | None:
        return self._by_domain.get(domain)

    def by_mx_domain(self, domain: str) -> Preset | None:
        return self._by_mx.get(domain)

    def server_hosts(self) -> frozenset[str]:
        """Every server host named in a preset."""
        return frozenset(
            server.host
            for preset in self.all
            for candidate in preset.candidates
            for server in candidate.servers
        )


@cache
def bundled() -> Presets:
    """The presets that ship with the service."""
    text = resources.files(__package__).joinpath("presets.json").read_text("utf-8")
    return Presets(_File.model_validate_json(text).providers)


class PresetSource:
    name = DiscoverySourceName.PRESET

    def __init__(self, presets: Presets | None = None) -> None:
        self._presets = presets or bundled()

    async def lookup(self, query: Query) -> Finding:
        preset = self._presets.by_domain(query.domain)
        return preset.finding(self.name) if preset else Finding()
