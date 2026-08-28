import json
import ssl
from collections import defaultdict
from collections.abc import Callable, Iterable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen

from config import (
    FPL_API_URL,
    HEADSHOTS,
    LEAGUE_ID,
    PAIRINGS,
    PUBLIC_DIR,
    TEAM_CARD_IMAGE,
)

JsonObject = dict[str, Any]
JsonFetcher = Callable[[str], JsonObject]
FIXTURE_TIMEZONE = timezone(timedelta(hours=8))
try:
    import certifi
except ImportError:  # pragma: no cover - depends on deployment environment
    SSL_CONTEXT = None
else:
    SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
CHIP_LABELS = {
    "bboost": "BB",
    "3xc": "TC",
    "freehit": "FH",
    "wildcard": "WC",
}
POSITION_SORT_ORDER = {
    1: 0,  # Goalkeepers
    2: 1,  # Defenders
    3: 2,  # Midfielders
    4: 3,  # Forwards
}
POINT_DETAIL_ORDER = {
    identifier: order
    for order, identifier in enumerate(
        (
            "goals_scored",
            "assists",
            "defensive_contribution",
            "clean_sheets",
            "saves",
            "penalties_saved",
            "minutes",
            "goals_conceded",
            "own_goals",
            "penalties_missed",
            "yellow_cards",
            "red_cards",
            "bonus",
        )
    )
}


def _get_json(url: str) -> JsonObject:
    request = Request(url, headers={"User-Agent": "fpl-league-site"})
    with urlopen(request, timeout=20, context=SSL_CONTEXT) as response:
        return json.load(response)


def _format_fixture_time(kickoff_time: str | None) -> str:
    if not kickoff_time:
        return "-"

    kickoff = datetime.fromisoformat(kickoff_time.replace("Z", "+00:00"))
    return kickoff.astimezone(FIXTURE_TIMEZONE).strftime("%a %H:%M")


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


def _fetch_chips(
    entries: Iterable[JsonObject], gameweek_id: int, fetch_json: JsonFetcher
) -> dict[int, str]:
    return {
        entry_id: chip
        for entry_id, chip in _format_chips(
            _fetch_entry_event_data(entries, gameweek_id, fetch_json)
        ).items()
        if chip is not None
    }


def _fetch_transfer_data(
    entries: Iterable[JsonObject], fetch_json: JsonFetcher
) -> dict[int, list[JsonObject]]:
    def fetch_transfers(entry: JsonObject) -> tuple[int, list[JsonObject]]:
        entry_id = entry["entry"]
        try:
            data = fetch_json(f"{FPL_API_URL}/entry/{entry_id}/transfers/")
        except Exception:
            data = []
        return entry_id, data if isinstance(data, list) else []

    entries = list(entries)
    if not entries:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(entries))) as executor:
        return dict(executor.map(fetch_transfers, entries))


def _fetch_entry_event_data(
    entries: Iterable[JsonObject], gameweek_id: int, fetch_json: JsonFetcher
) -> dict[int, JsonObject]:
    def fetch_event_data(entry: JsonObject) -> tuple[int, JsonObject | None]:
        entry_id = entry["entry"]
        try:
            data = fetch_json(f"{FPL_API_URL}/entry/{entry_id}/event/{gameweek_id}/picks/")
        except Exception:
            return entry_id, None
        return entry_id, data

    entries = list(entries)
    if not entries:
        return {}
    with ThreadPoolExecutor(max_workers=min(8, len(entries))) as executor:
        return {
            entry_id: data
            for entry_id, data in executor.map(fetch_event_data, entries)
            if data is not None
        }


def _format_chips(entry_event_data: dict[int, JsonObject]) -> dict[int, str | None]:
    return {
        entry_id: CHIP_LABELS.get(data.get("active_chip"))
        for entry_id, data in entry_event_data.items()
    }


def _player_name(element: JsonObject) -> str:
    return (
        element.get("web_name")
        or f'{element.get("first_name", "")} {element.get("second_name", "")}'.strip()
        or f'Player {element["id"]}'
    )


def _format_point_details(
    live_element: JsonObject, position: int | None
) -> JsonObject | None:
    stats = live_element.get("stats", {})
    if not stats.get("played"):
        return None

    details: dict[str, JsonObject] = {}
    for fixture in live_element.get("explain", []):
        for item in fixture.get("stats", []):
            identifier = item.get("identifier")
            if identifier not in POINT_DETAIL_ORDER:
                continue
            detail = details.setdefault(
                identifier,
                {"identifier": identifier, "value": 0, "points": 0},
            )
            detail["value"] += item.get("value", 0)
            detail["points"] += item.get("points", 0)

    if position in (2, 3, 4) and "defensive_contribution" not in details:
        details["defensive_contribution"] = {
            "identifier": "defensive_contribution",
            "value": stats.get("defensive_contribution", 0),
            "points": 0,
        }

    if "bonus" in details:
        details["bonus"]["bps"] = stats.get("bps", 0)

    return {
        "rows": sorted(
            details.values(),
            key=lambda detail: POINT_DETAIL_ORDER[detail["identifier"]],
        ),
        "total": stats.get("total_points", 0),
    }


def _build_player_context(
    elements: Iterable[JsonObject],
    teams: Iterable[JsonObject],
    fixtures: Iterable[JsonObject],
    live_elements: Iterable[JsonObject],
) -> tuple[dict[int, JsonObject], Callable[[int], tuple[str, str, int | str]]]:
    players = {
        element["id"]: {
            "name": _player_name(element),
            "team": element.get("team"),
            "position": element.get("element_type"),
        }
        for element in elements
    }
    team_names = {team["id"]: team.get("short_name", team.get("name", "")) for team in teams}
    live_points = {
        element["id"]: element.get("stats", {}).get("total_points", 0)
        for element in live_elements
    }
    live_by_player = {element["id"]: element for element in live_elements}
    for player_id, player in players.items():
        player["pointDetails"] = _format_point_details(
            live_by_player.get(player_id, {}), player.get("position")
        )

    fixtures_by_team: dict[int, list[JsonObject]] = defaultdict(list)
    for fixture in fixtures:
        home_id = fixture["team_h"]
        away_id = fixture["team_a"]
        finished = bool(fixture.get("finished") or fixture.get("finished_provisional"))
        started = bool(fixture.get("started") or finished)
        fixtures_by_team[home_id].append(
            {
                "opponent": team_names.get(away_id, str(away_id)),
                "venue": "H",
                "started": started,
                "finished": finished,
                "time": _format_fixture_time(fixture.get("kickoff_time")),
            }
        )
        fixtures_by_team[away_id].append(
            {
                "opponent": team_names.get(home_id, str(home_id)),
                "venue": "A",
                "started": started,
                "finished": finished,
                "time": _format_fixture_time(fixture.get("kickoff_time")),
            }
        )

    def player_context(player_id: int) -> tuple[str, str, int | str]:
        player = players.get(player_id, {})
        player_fixtures = fixtures_by_team.get(player.get("team"), [])
        if not player_fixtures:
            return "-", "-", "-"

        opponent = ", ".join(
            f'{fixture["opponent"]} ({fixture["venue"]})'
            for fixture in player_fixtures
        )
        fixture_time = (
            "Done"
            if any(fixture["finished"] for fixture in player_fixtures)
            else ", ".join(fixture["time"] for fixture in player_fixtures)
        )
        points = live_points.get(player_id, 0) if any(
            fixture["started"] for fixture in player_fixtures
        ) else "-"
        return opponent, fixture_time, points

    return players, player_context


def _format_player_ownership(
    entries: Iterable[JsonObject],
    gameweek_id: int,
    elements: Iterable[JsonObject],
    fetch_json: JsonFetcher,
) -> list[JsonObject]:
    entries = list(entries)
    if not entries:
        return []

    player_names = {
        element["id"]: element.get("web_name")
        or f'{element.get("first_name", "")} {element.get("second_name", "")}'.strip()
        for element in elements
    }

    def fetch_picks(entry: JsonObject) -> list[JsonObject] | None:
        try:
            data = fetch_json(
                f"{FPL_API_URL}/entry/{entry['entry']}/event/{gameweek_id}/picks/"
            )
        except Exception:
            return None
        return data.get("picks", [])

    owned = defaultdict(int)
    effective = defaultdict(int)
    team_count = 0
    with ThreadPoolExecutor(max_workers=min(8, len(entries))) as executor:
        for picks in executor.map(fetch_picks, entries):
            if picks is None:
                continue
            team_count += 1
            for pick in picks:
                player_id = pick["element"]
                owned[player_id] += 1
                effective[player_id] += pick.get("multiplier", 0)

    if team_count == 0:
        return []

    ownership = [
        {
            "id": player_id,
            "name": player_names.get(player_id, f"Player {player_id}"),
            "ownership": round(owned_count / team_count * 100, 1),
            "effectiveOwnership": round(effective[player_id] / team_count * 100, 1),
        }
        for player_id, owned_count in owned.items()
    ]
    ownership.sort(
        key=lambda player: (
            -player["effectiveOwnership"],
            -player["ownership"],
            player["name"],
        )
    )
    return ownership


def _format_duo_importance(
    pairs: Iterable[JsonObject],
    gameweek_id: int,
    elements: Iterable[JsonObject],
    teams: Iterable[JsonObject],
    fixtures: Iterable[JsonObject],
    live_elements: Iterable[JsonObject],
    fetch_json: JsonFetcher,
) -> list[JsonObject]:
    pairs = list(pairs)
    if not pairs:
        return []

    players, player_context = _build_player_context(
        elements, teams, fixtures, live_elements
    )

    pick_cache: dict[int, list[JsonObject]] = {}

    def picks_for_entry(entry_id: int) -> list[JsonObject]:
        if entry_id not in pick_cache:
            try:
                data = fetch_json(
                    f"{FPL_API_URL}/entry/{entry_id}/event/{gameweek_id}/picks/"
                )
            except Exception:
                data = {"picks": []}
            pick_cache[entry_id] = data.get("picks", [])
        return pick_cache[entry_id]

    player_team_breakdown: dict[int, JsonObject] = defaultdict(
        lambda: {"started": [], "benched": []}
    )
    seen_entries: set[int] = set()
    for pair in pairs:
        for member in pair["members"]:
            entry_id = member["id"]
            if entry_id in seen_entries:
                continue
            seen_entries.add(entry_id)
            team_name = member.get("team") or member.get("manager") or f"Team {entry_id}"
            for pick in picks_for_entry(entry_id):
                player_id = pick["element"]
                multiplier = pick.get("multiplier", 0)
                if multiplier > 0:
                    player_team_breakdown[player_id]["started"].append(
                        {"name": team_name, "captain": multiplier > 1}
                    )
                else:
                    player_team_breakdown[player_id]["benched"].append(
                        {"name": team_name}
                    )

    pair_data = []
    for pair in pairs:
        owned: set[int] = set()
        exposure: dict[int, int] = defaultdict(int)
        for member in pair["members"]:
            for pick in picks_for_entry(member["id"]):
                player_id = pick["element"]
                owned.add(player_id)
                exposure[player_id] += pick.get("multiplier", 0)
        pair_data.append({"name": pair["name"], "owned": owned, "exposure": exposure})

    comparison_pairs = pair_data[:50]
    all_owned = set().union(*(pair["owned"] for pair in pair_data))

    importance_by_duo = []
    for selected in pair_data:
        comparison = [
            pair for pair in comparison_pairs if pair["name"] != selected["name"]
        ]
        rows = []
        for player_id in all_owned:
            selected_exposure = selected["exposure"].get(player_id, 0) * 100
            average_exposure = (
                sum(pair["exposure"].get(player_id, 0) * 100 for pair in comparison)
                / len(comparison)
                if comparison
                else 0
            )
            opponent, fixture_time, points = player_context(player_id)
            rows.append(
                {
                    "id": player_id,
                    "name": players.get(player_id, {}).get("name", f"Player {player_id}"),
                    "opponent": opponent,
                    "fixtureTime": fixture_time,
                    "points": points,
                    "pointDetails": players.get(player_id, {}).get("pointDetails"),
                    "importance": round(selected_exposure - average_exposure, 1),
                    "teams": player_team_breakdown.get(
                        player_id, {"started": [], "benched": []}
                    ),
                }
            )

        rows.sort(key=lambda player: (-player["importance"], player["name"]))
        importance_by_duo.append({"name": selected["name"], "players": rows})

    return importance_by_duo


def _format_team_value(value: int | float | None) -> float | None:
    if not isinstance(value, int | float):
        return None
    return round(value / 10, 1)


def _format_bank(entry_history: JsonObject, picks: Iterable[JsonObject]) -> float | None:
    bank = entry_history.get("bank")
    if isinstance(bank, int | float):
        return _format_team_value(bank)

    value = entry_history.get("value")
    selling_prices = [pick.get("selling_price") for pick in picks]
    if not isinstance(value, int | float) or not selling_prices:
        return None
    if not all(isinstance(price, int | float) for price in selling_prices):
        return None

    return _format_team_value(value - sum(selling_prices))


def _format_transfers(
    transfers: Iterable[JsonObject],
    gameweek_id: int,
    players: dict[int, JsonObject],
) -> list[JsonObject]:
    formatted = []
    for transfer in transfers:
        if transfer.get("event") != gameweek_id:
            continue

        player_in_id = transfer.get("element_in")
        player_out_id = transfer.get("element_out")
        formatted.append(
            {
                "in": players.get(player_in_id, {}).get(
                    "name", f"Player {player_in_id}"
                ),
                "out": players.get(player_out_id, {}).get(
                    "name", f"Player {player_out_id}"
                ),
                "time": transfer.get("time"),
            }
        )

    formatted.sort(key=lambda transfer: transfer.get("time") or "")
    return formatted


def _format_team_details(
    standings: Iterable[JsonObject],
    entry_event_data: dict[int, JsonObject],
    transfer_data: dict[int, list[JsonObject]],
    gameweek_id: int,
    elements: Iterable[JsonObject],
    teams: Iterable[JsonObject],
    fixtures: Iterable[JsonObject],
    live_elements: Iterable[JsonObject],
) -> list[JsonObject]:
    standings = list(standings)
    if not standings:
        return []

    players, player_context = _build_player_context(
        elements, teams, fixtures, live_elements
    )
    team_exposure: dict[int, dict[int, int]] = {}
    player_team_breakdown: dict[int, JsonObject] = defaultdict(
        lambda: {"started": [], "benched": []}
    )
    for team in standings:
        entry_id = team["id"]
        team_name = team.get("team") or team.get("manager") or f"Team {entry_id}"
        exposure: dict[int, int] = defaultdict(int)
        for pick in entry_event_data.get(entry_id, {}).get("picks", []):
            player_id = pick["element"]
            multiplier = pick.get("multiplier", 0)
            exposure[player_id] += multiplier
            if multiplier > 0:
                player_team_breakdown[player_id]["started"].append(
                    {"name": team_name, "captain": multiplier > 1}
                )
            else:
                player_team_breakdown[player_id]["benched"].append(
                    {"name": team_name}
                )
        team_exposure[entry_id] = exposure

    team_details = []
    comparison_limit = standings[:50]
    for team in standings:
        entry_id = team["id"]
        event_data = entry_event_data.get(entry_id, {})
        entry_history = event_data.get("entry_history", {})
        event_picks = event_data.get("picks", [])
        comparison = [
            comparison_team
            for comparison_team in comparison_limit
            if comparison_team["id"] != entry_id
        ]
        picks = []

        for pick in event_picks:
            player_id = pick["element"]
            player = players.get(player_id, {})
            selected_exposure = team_exposure.get(entry_id, {}).get(player_id, 0) * 100
            average_exposure = (
                sum(
                    team_exposure.get(comparison_team["id"], {}).get(player_id, 0)
                    * 100
                    for comparison_team in comparison
                )
                / len(comparison)
                if comparison
                else 0
            )
            opponent, fixture_time, points = player_context(player_id)
            multiplier = pick.get("multiplier", 0)
            picks.append(
                {
                    "id": player_id,
                    "name": player.get("name", f"Player {player_id}"),
                    "opponent": opponent,
                    "fixtureTime": fixture_time,
                    "points": points,
                    "pointDetails": player.get("pointDetails"),
                    "importance": round(selected_exposure - average_exposure, 1),
                    "position": player.get("position"),
                    "pickPosition": pick.get("position"),
                    "multiplier": multiplier,
                    "isCaptain": bool(pick.get("is_captain")),
                    "isViceCaptain": bool(pick.get("is_vice_captain")),
                    "isBenched": multiplier == 0,
                    "teams": player_team_breakdown.get(
                        player_id, {"started": [], "benched": []}
                    ),
                }
            )

        picks.sort(
            key=lambda pick: (
                1 if (pick.get("pickPosition") or 99) > 11 else 0,
                POSITION_SORT_ORDER.get(pick.get("position"), 99),
                pick.get("pickPosition") or 99,
                pick["name"],
            )
        )
        team_details.append(
            {
                "id": entry_id,
                "team": team["team"],
                "manager": team["manager"],
                "gameweekPoints": team["gameweekPoints"],
                "totalPoints": team["totalPoints"],
                "transfersMade": entry_history.get("event_transfers", 0),
                "transferCost": entry_history.get("event_transfers_cost", 0),
                "transfers": _format_transfers(
                    transfer_data.get(entry_id, []), gameweek_id, players
                ),
                "chip": CHIP_LABELS.get(event_data.get("active_chip")),
                "teamValue": _format_team_value(entry_history.get("value")),
                "bank": _format_bank(entry_history, event_picks),
                "players": picks,
            }
        )

    return team_details


def _format_standings(
    entries: Iterable[JsonObject],
    gameweek_id: int,
    badges: dict[int, str] | None = None,
    chips: dict[int, str] | None = None,
) -> list[JsonObject]:
    badges = badges or {}
    chips = chips or {}
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
                "chip": chips.get(entry["entry"]),
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
    entry_event_data = _fetch_entry_event_data(entries, gameweek["id"], fetch_json)
    transfer_data = _fetch_transfer_data(entries, fetch_json)
    chips = _format_chips(entry_event_data)
    standings = _format_standings(entries, gameweek["id"], badges, chips)
    pairs = _format_pairs(standings, pairings)
    fixtures = (
        fetch_json(f"{FPL_API_URL}/fixtures/?event={gameweek['id']}")
        if standings
        else []
    )
    live = fetch_json(f"{FPL_API_URL}/event/{gameweek['id']}/live/") if standings else {}
    duo_importance = _format_duo_importance(
        pairs,
        gameweek["id"],
        bootstrap["elements"],
        bootstrap.get("teams", []),
        fixtures,
        live.get("elements", []),
        fetch_json,
    )
    team_details = _format_team_details(
        standings,
        entry_event_data,
        transfer_data,
        gameweek["id"],
        bootstrap["elements"],
        bootstrap.get("teams", []),
        fixtures,
        live.get("elements", []),
    )

    return {
        "league": {"id": league["id"], "name": league["name"]},
        "gameweek": {"id": gameweek["id"], "name": gameweek["name"]},
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "teamCardImage": TEAM_CARD_IMAGE,
        "standings": standings,
        "pairs": pairs,
        "duoImportance": duo_importance,
        "teamDetails": team_details,
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
