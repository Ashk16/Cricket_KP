"""Persist reference entities (teams, venue, players) and the match itself
from a Sportmonks fixture payload.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from db.models import Innings, Match, Player, Team, Venue
from live.sportmonks_client import _unwrap_obj
from timeutils import to_ist


def parse_utc(value: Any) -> Optional[datetime]:
    """Parse a Sportmonks datetime string into a naive UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value
    s = str(value).strip().replace("Z", "+00:00")
    # Sportmonks sometimes uses a space separator instead of 'T'.
    if " " in s and "T" not in s:
        s = s.replace(" ", "T", 1)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                dt = datetime.strptime(str(value)[:19], fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def ensure_team(session: Session, sportmonks_id: Optional[int], name: Optional[str] = None,
                code: Optional[str] = None) -> Optional[Team]:
    if sportmonks_id is None:
        return None
    team = session.scalar(select(Team).where(Team.sportmonks_id == sportmonks_id))
    if team is None:
        team = Team(sportmonks_id=sportmonks_id, name=name or f"team_{sportmonks_id}", code=code)
        session.add(team)
        session.flush()
    elif name and team.name.startswith("team_"):
        team.name = name
    return team


def ensure_player(session: Session, sportmonks_id: Optional[int], name: Optional[str] = None) -> Optional[Player]:
    if sportmonks_id is None:
        return None
    player = session.scalar(select(Player).where(Player.sportmonks_id == sportmonks_id))
    if player is None:
        player = Player(sportmonks_id=sportmonks_id, name=name or f"player_{sportmonks_id}")
        session.add(player)
        session.flush()
    elif name:
        if player.name.startswith("player_") or player.name == f"player_{sportmonks_id}":
            player.name = name
    return player


def ensure_venue(session: Session, venue_payload: Dict[str, Any]) -> Optional[Venue]:
    venue_payload = _unwrap_obj(venue_payload)
    if not venue_payload:
        return None
    sm_id = venue_payload.get("id")
    venue = session.scalar(select(Venue).where(Venue.sportmonks_id == sm_id)) if sm_id else None
    lat = _first(venue_payload, "lat", "latitude")
    lon = _first(venue_payload, "lon", "lng", "longitude")
    if venue is None:
        venue = Venue(
            sportmonks_id=sm_id,
            name=venue_payload.get("name", "unknown"),
            city=venue_payload.get("city"),
            country=venue_payload.get("country"),
            lat=_safe_float(lat),
            lon=_safe_float(lon),
        )
        session.add(venue)
        session.flush()
    return venue


def ensure_match_from_fixture(
    session: Session,
    fixture: Dict[str, Any],
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    fmt: Optional[str] = None,
) -> Match:
    """Create/update a Match (plus teams + venue) from a fixture payload.

    lat/lon override the venue coordinates (needed when Sportmonks doesn't
    expose venue geo-coordinates).
    """
    fixture_id = fixture.get("id")
    match = session.scalar(select(Match).where(Match.sportmonks_fixture_id == fixture_id))

    local = _unwrap_obj(fixture.get("localteam"))
    visitor = _unwrap_obj(fixture.get("visitorteam"))
    local_team = ensure_team(session, fixture.get("localteam_id") or local.get("id"),
                             local.get("name"), local.get("code"))
    visitor_team = ensure_team(session, fixture.get("visitorteam_id") or visitor.get("id"),
                               visitor.get("name"), visitor.get("code"))
    venue = ensure_venue(session, fixture.get("venue"))

    resolved_lat = lat if lat is not None else (venue.lat if venue else None)
    resolved_lon = lon if lon is not None else (venue.lon if venue else None)

    if match is None:
        match = Match(sportmonks_fixture_id=fixture_id)
        session.add(match)

    match.format = fmt or fixture.get("type")
    match.league = _maybe_str(fixture.get("league_id"))
    match.season = _maybe_str(fixture.get("season_id"))
    match.localteam_id = local_team.id if local_team else None
    match.visitorteam_id = visitor_team.id if visitor_team else None
    match.venue_id = venue.id if venue else None
    match.starting_at_utc = parse_utc(fixture.get("starting_at"))
    match.starting_at_ist = to_ist(match.starting_at_utc)
    match.lat = resolved_lat
    match.lon = resolved_lon
    match.status = fixture.get("status")
    match.result_note = fixture.get("note")
    apply_match_outcome(session, match, fixture)
    session.flush()
    return match


def apply_match_outcome(session: Session, match: Match, fixture: Dict[str, Any]) -> None:
    """Map Sportmonks winner/toss ids to local team ids."""
    def local_team_id(sm_id: Any) -> Optional[int]:
        if sm_id is None:
            return None
        team = session.scalar(select(Team).where(Team.sportmonks_id == sm_id))
        return team.id if team else None

    winner = local_team_id(fixture.get("winner_team_id"))
    toss_won = local_team_id(fixture.get("toss_won_team_id"))
    if winner is not None:
        match.winner_team_id = winner
    if toss_won is not None:
        match.toss_won_team_id = toss_won
    elected = fixture.get("elected")
    if elected:
        match.toss_elected = str(elected)


def _chose_to_bat(toss_elected: Optional[str]) -> Optional[bool]:
    elected = str(toss_elected or "").lower().strip()
    if elected.startswith("bat"):
        return True
    if elected.startswith("bowl") or elected == "field":
        return False
    return None


def batting_team_for_innings(
    innings_number: int,
    *,
    localteam_id: Optional[int],
    visitorteam_id: Optional[int],
    toss_won_team_id: Optional[int] = None,
    toss_elected: Optional[str] = None,
    innings_batting_team_id: Optional[int] = None,
) -> Optional[int]:
    """Resolve batting team for an innings (1st / 2nd)."""
    if innings_batting_team_id:
        return innings_batting_team_id
    if not localteam_id or not visitorteam_id:
        return localteam_id or visitorteam_id

    chose_bat = _chose_to_bat(toss_elected)
    if toss_won_team_id and chose_bat is not None:
        other = visitorteam_id if toss_won_team_id == localteam_id else localteam_id
        first_bat = toss_won_team_id if chose_bat else other
    else:
        first_bat = localteam_id

    if innings_number == 1:
        return first_bat
    return visitorteam_id if first_bat == localteam_id else localteam_id


def apply_innings_batting_teams(session: Session, match: Match) -> None:
    """Fill batting_team_id on innings rows from toss + innings number."""
    innings_list = session.scalars(
        select(Innings).where(Innings.match_id == match.id)
    ).all()
    for inn in innings_list:
        bat_id = batting_team_for_innings(
            inn.innings_number,
            localteam_id=match.localteam_id,
            visitorteam_id=match.visitorteam_id,
            toss_won_team_id=match.toss_won_team_id,
            toss_elected=match.toss_elected,
            innings_batting_team_id=inn.batting_team_id,
        )
        if bat_id is not None:
            inn.batting_team_id = bat_id
    session.flush()


def apply_coordinates(
    session: Session,
    match: Match,
    venue_payload: Dict[str, Any],
    allow_ai: bool = True,
    force: bool = False,
):
    """Resolve and store venue coordinates on the match (and venue row).

    Library-first, OpenAI fallback. Skips work if the match already has coords
    (unless force=True). Returns the CoordResult.
    """
    from live.venue_coords import CoordResult, resolve_coordinates

    if not force and match.lat is not None and match.lon is not None:
        return CoordResult(match.lat, match.lon, "existing")

    result = resolve_coordinates(venue_payload, allow_ai=allow_ai)
    if result.resolved:
        match.lat = result.lat
        match.lon = result.lon
        if match.venue_id is not None:
            venue = session.get(Venue, match.venue_id)
            if venue is not None:
                if venue.lat is None or force:
                    venue.lat = result.lat
                    venue.lon = result.lon
                venue.coords_source = result.source
        session.flush()
    return result


def apply_manual_ground(
    session: Session,
    match: Match,
    ground: Dict[str, Any],
) -> None:
    """Attach a library ground chosen in the live dashboard when Sportmonks venue is null."""
    key = ground.get("key")
    sm_id = int(key) if key is not None and str(key).isdigit() else None
    payload = {
        "id": sm_id,
        "name": ground.get("name") or "unknown",
        "city": ground.get("city") or None,
        "lat": ground.get("lat"),
        "lon": ground.get("lon"),
    }
    venue = ensure_venue(session, payload)
    if venue is not None:
        venue.name = payload["name"]
        if payload["city"]:
            venue.city = payload["city"]
        venue.lat = float(ground["lat"])
        venue.lon = float(ground["lon"])
        venue.coords_source = "manual"
        match.venue_id = venue.id
    match.lat = float(ground["lat"])
    match.lon = float(ground["lon"])
    session.flush()


def _first(d: Dict[str, Any], *keys):
    for k in keys:
        if d.get(k) is not None:
            return d[k]
    return None


def _safe_float(value) -> Optional[float]:
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _maybe_str(value) -> Optional[str]:
    return None if value is None else str(value)
