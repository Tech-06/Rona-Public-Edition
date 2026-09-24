"""Tunable thresholds for the memory consolidation engine.

Every field mirrors a `Settings.memory_*` field one-to-one (same name
minus the `memory_` prefix, same default) so `.env` stays the single
source of truth; `MemoryPolicy` is just a typed, frozen snapshot of those
settings that the consolidation engine can pass around and log
without re-reading `Settings` mid-run.

Import rule: see memory/__init__.py -- `current_policy()` reads
`app.config` lazily, inside the function body.
"""

from __future__ import annotations

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class MemoryPolicy:
    consolidation_interval_hours: int = 24
    auto_promote_enabled: bool = True
    auto_archive_enabled: bool = True
    auto_delete_enabled: bool = True
    short_promote_hits: int = 3
    seasonal_promote_hits: int = 10
    seasonal_archive_days: int = 90
    short_delete_days: int = 7
    short_delete_below_hits: int = 3
    access_top_n: int = 3
    access_cooldown_hours: int = 12

    @classmethod
    def from_settings(cls, settings: object) -> MemoryPolicy:
        return cls(
            **{
                field.name: getattr(settings, f"memory_{field.name}")
                for field in fields(cls)
            }
        )

    def as_dict(self) -> dict:
        return {field.name: getattr(self, field.name) for field in fields(self)}


def current_policy() -> MemoryPolicy:
    """The policy in effect right now, read from `Settings`."""
    from app.config import get_settings

    return MemoryPolicy.from_settings(get_settings())
