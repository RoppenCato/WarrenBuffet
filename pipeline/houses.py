"""Which auction houses we track, and which house an own scan belongs to (plan/houses.yaml)."""
from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "plan" / "houses.yaml"


def _config(path: Path = CONFIG) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def tracked(path: Path = CONFIG) -> list[str]:
    return list(_config(path).get("tracked") or [])


def house_id(realm: str, faction: str, path: Path = CONFIG) -> str | None:
    """House id for a scan header, or None when the realm is not in plan/houses.yaml yet."""
    realm_info = (_config(path).get("realms") or {}).get(realm)
    if not realm_info or faction.lower() not in ("horde", "alliance"):
        return None
    return f"forever.{realm_info['ruleset']}.{faction.lower()}.{realm_info['region']}"
