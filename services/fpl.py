import json
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from config import FPL_API_URL, HEADSHOTS, LEAGUE_ID, PAIRINGS, PUBLIC_DIR

JsonObject = dict[str, Any]
JsonFetcher = Callable[[str], JsonObject]


def _get_json(url: str) -> JsonObject:
    request = Request(url, headers={"User-Agent": "fpl-league-site"})
    with urlopen(request, timeout=20) as response:
        return json.load(response)


def _select_gameweek(events: Iterable[JsonObject]) -> JsonObject:
    events = list(events)
    gameweek = next((event for event in events if event["is_current"]), None)
    gameweek = gameweek or next(
        (event for event in reversed(events) if event["finished"]), None
    )
    gameweek = gameweek or next((event for event in events if event["is_next"]), None)

    if gameweek is None:
        raise RuntimeError("No FPL gameweek found")
    return gameweek


def _fetch_league(fetch_json: JsonFetcher) -> tuple[JsonObject, list[JsonObject]]:
    page_number: int | None = 1
    league: JsonObject | None = None
    entries: list[JsonObject] = []
    new_entries: list[JsonObject] = []

    while page_number is not None:
        data = fetch_json(
            f"{FPL_API_URL}/leagues-classic/{LEAGUE_ID}/standings/"
            f"?page_standings={page_number}"
        )
        league = data["league"]
        if page_number == 1:
            new_entries = data["new_entries"]["results"]

        standings = data["standings"]
        entries.extend(standings["results"])
        page_number = page_number + 1 if standings["has_next"] else None

    if league is None or not (entries or new_entries):
        raise RuntimeError("League returned no teams")

    seen_entry_ids = {entry["entry"] for entry in entries}
    entries.extend(
        entry for entry in new_entries if entry["entry"] not in seen_entry_ids
    )
    return league, entries


def _team_url(entry_id: int, gameweek_id: int) -> str:
    return f"https://fantasy.premierleague.com/entry/{entry_id}/event/{gameweek_id}"


def _fetch_badges(
    entries: Iterable[JsonObject], fetch_json: JsonFetcher
) -> dict[int, str]:
    def fetch_badge(entry: JsonObject) -> tuple[int, str | None]:
        entry_id = entry["entry"]
        try:
            entry_data = fetch_json(f"{FPL_API_URL}/entry/{entry_id}/")
        except Exception:
            return entry_id, None

        badge_url = entry_data.get("club_badge_src")
        if badge_url and badge_url != "Pending":
            return entry_id, badge_url
        return entry_id, None

    entries = list(entries)
    if not entries:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(entries))) as executor:
        return {
            entry_id: badge_url
            for entry_id, badge_url in executor.map(fetch_badge, entries)
            if badge_url is not None
        }


def _format_standings(
    entries: Iterable[JsonObject],
    gameweek_id: int,
    badges: dict[int, str] | None = None,
) -> list[JsonObject]:
    badges = badges or {}
    standings = []
    for entry in entries:
        is_ranked = "rank" in entry
        manager = (
            entry["player_name"]
            if is_ranked
            else f'{entry["player_first_name"]} {entry["player_last_name"]}'.strip()
        )
        standings.append(
            {
                "id": entry["entry"],
                "rank": entry["rank"] if is_ranked else "—",
                "team": entry["entry_name"],
                "manager": manager,
                "gameweekPoints": entry["event_total"] if is_ranked else "—",
                "totalPoints": entry["total"] if is_ranked else "—",
                "url": _team_url(entry["entry"], gameweek_id),
                "badgeUrl": badges.get(entry["entry"]),
                "headshotUrl": HEADSHOTS.get(entry["entry"]),
            }
        )
    return standings


def _format_pairs(
    standings: Iterable[JsonObject],
    pairings: Iterable[tuple[str, tuple[int, int]]] = PAIRINGS,
) -> list[JsonObject]:
    teams_by_id = {team["id"]: team for team in standings}
    pairs = []

    for name, entry_ids in pairings:
        missing_ids = [entry_id for entry_id in entry_ids if entry_id not in teams_by_id]
        if missing_ids:
            raise RuntimeError(f"Pair {name} is missing FPL entry {missing_ids[0]}")

        members = [teams_by_id[entry_id] for entry_id in entry_ids]

        def combined(field: str) -> int | str:
            values = [member[field] for member in members]
            return sum(values) if all(isinstance(value, int) for value in values) else "—"

        pairs.append(
            {
                "name": name,
                "members": members,
                "gameweekPoints": combined("gameweekPoints"),
                "totalPoints": combined("totalPoints"),
            }
        )

    pairs.sort(
        key=lambda pair: (
            isinstance(pair["totalPoints"], int),
            pair["totalPoints"] if isinstance(pair["totalPoints"], int) else 0,
        ),
        reverse=True,
    )

    previous_total = None
    previous_rank = None
    for position, pair in enumerate(pairs, start=1):
        total = pair["totalPoints"]
        if not isinstance(total, int):
            pair["rank"] = "—"
        elif total == previous_total:
            pair["rank"] = previous_rank
        else:
            pair["rank"] = position
            previous_total = total
            previous_rank = position

    return pairs


def _write_json(data: JsonObject, destination: Path) -> None:
    destination.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def fetch_standings(
    *,
    fetch_json: JsonFetcher | None = None,
    pairings: Iterable[tuple[str, tuple[int, int]]] = PAIRINGS,
) -> JsonObject:
    fetch_json = fetch_json or _get_json

    bootstrap = fetch_json(f"{FPL_API_URL}/bootstrap-static/")
    gameweek = _select_gameweek(bootstrap["events"])
    league, entries = _fetch_league(fetch_json)
    badges = _fetch_badges(entries, fetch_json)

    standings = _format_standings(entries, gameweek["id"], badges)
    return {
        "league": {"id": league["id"], "name": league["name"]},
        "gameweek": {"id": gameweek["id"], "name": gameweek["name"]},
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "standings": standings,
        "pairs": _format_pairs(standings, pairings),
    }


def update_standings(
    *,
    fetch_json: JsonFetcher | None = None,
    destination: Path | None = None,
    pairings: Iterable[tuple[str, tuple[int, int]]] = PAIRINGS,
) -> JsonObject:
    output = fetch_standings(fetch_json=fetch_json, pairings=pairings)
    destination = destination or PUBLIC_DIR / "standings.json"
    _write_json(output, destination)
    return output
