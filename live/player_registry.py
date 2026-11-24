"""Resolve and persist Sportmonks player names for analysis."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterable, Optional, Set

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Player
from live.match_setup import ensure_player
from live.sportmonks_client import SportmonksClient, SportmonksError, _unwrap_list

logger = logging.getLogger("kp.players")


def _player_ids_from_fixture(detail: Dict[str, Any], balls_raw: Optional[Iterable[Dict[str, Any]]] = None) -> Set[int]:
    """Collect Sportmonks player ids from batting, bowling, and ball rows."""
    ids: Set[int] = set()
    for key in ("batting", "bowling"):
        for row in _unwrap_list(detail.get(key)):
            pid = row.get("player_id")
            if pid is not None:
                ids.add(int(pid))
    for ball in balls_raw or ():
        for key in ("batsman_id", "batsmanone_id", "bowler_id"):
            pid = ball.get(key)
            if pid is not None:
                ids.add(int(pid))
    return ids


def sync_players_from_fixture(
    session: Session,
    client: SportmonksClient,
    detail: Dict[str, Any],
    balls_raw: Optional[Iterable[Dict[str, Any]]] = None,
) -> int:
    """Ensure all players in a fixture exist with real names. Returns count updated."""
    updated = 0
    for sm_id in _player_ids_from_fixture(detail, balls_raw):
        name = client.get_player_name(sm_id)
        player = ensure_player(session, sm_id, name=name)
        if player is not None and name and not player.name.startswith("player_"):
            updated += 1
    return updated


def enrich_placeholder_players(
    session: Session,
    client: SportmonksClient,
    *,
    limit: Optional[int] = None,
    progress_every: int = 100,
    retries: int = 3,
) -> Dict[str, int]:
    """Fetch names from Sportmonks for players still stored as player_{id}."""
    placeholders = list(
        session.scalars(
            select(Player)
            .where(Player.sportmonks_id.is_not(None), Player.name.like("player_%"))
            .order_by(Player.id)
        ).all()
    )
    if limit is not None:
        placeholders = placeholders[:limit]

    stats = {"seen": len(placeholders), "resolved": 0, "failed": 0, "skipped": 0}
    for i, player in enumerate(placeholders, 1):
        if not player.name.startswith("player_"):
            stats["skipped"] += 1
            continue
        name: Optional[str] = None
        for attempt in range(retries):
            try:
                name = client.get_player_name(int(player.sportmonks_id))
                break
            except Exception as exc:  # noqa: BLE001
                if attempt + 1 >= retries:
                    logger.warning("Player %s lookup failed: %s", player.sportmonks_id, exc)
                else:
                    time.sleep(1.5 * (attempt + 1))
        if name:
            player.name = name
            stats["resolved"] += 1
        else:
            stats["failed"] += 1
        if i % progress_every == 0:
            session.commit()
            logger.info("  %d/%d resolved=%d failed=%d", i, len(placeholders), stats["resolved"], stats["failed"])
    session.commit()
    return stats
