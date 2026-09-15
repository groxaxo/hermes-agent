from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Iterable, Mapping


class ModelTier(str, Enum):
    STANDARD = "standard"
    ADVANCED = "advanced"
    MAXIMUM = "maximum"


@dataclass(frozen=True)
class ProviderRoute:
    provider: str
    model: str
    tier: ModelTier
    priority: int = 100


class ProviderRouter:
    """AAIT-owned provider selection contract.

    Hermes can continue using its native provider stack today.  Product code
    should depend on these logical tiers instead of hard-coding vendor model
    names, making OpenAI, Bedrock, Z.ai, or a future provider replaceable.
    """

    def __init__(self, routes: Iterable[ProviderRoute]):
        self._routes = tuple(sorted(routes, key=lambda route: (route.tier.value, route.priority)))

    def routes_for(self, tier: ModelTier | str) -> tuple[ProviderRoute, ...]:
        selected = ModelTier(tier)
        return tuple(route for route in self._routes if route.tier == selected)

    def choose(
        self,
        tier: ModelTier | str,
        *,
        unavailable_providers: set[str] | None = None,
    ) -> ProviderRoute:
        unavailable = unavailable_providers or set()
        for route in self.routes_for(tier):
            if route.provider not in unavailable:
                return route
        raise LookupError(f"No healthy provider route configured for tier={ModelTier(tier).value}")

    @classmethod
    def from_mapping(cls, data: Mapping[str, object] | None) -> "ProviderRouter":
        routes: list[ProviderRoute] = []
        if not isinstance(data, Mapping):
            return cls(routes)
        raw_routes = data.get("routes", [])
        if not isinstance(raw_routes, list):
            return cls(routes)
        for item in raw_routes:
            if not isinstance(item, Mapping):
                continue
            provider = str(item.get("provider", "")).strip()
            model = str(item.get("model", "")).strip()
            if not provider or not model:
                continue
            routes.append(
                ProviderRoute(
                    provider=provider,
                    model=model,
                    tier=ModelTier(str(item.get("tier", "standard")).lower()),
                    priority=int(item.get("priority", 100)),
                )
            )
        return cls(routes)
