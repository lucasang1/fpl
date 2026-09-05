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
    GAMEWEEK_SNAPSHOT_DIR,
    HEADSHOTS,
    LEAGUE_ID,
    PAIRINGS,
    PUBLIC_DIR,
    TEAM_CARD_IMAGE,
)

JsonObject = dict[str, Any]
JsonFetcher = Callable[[str], JsonObject]
FIXTURE_TIMEZONE = timezone(timedelta(hours=8))
LIVE_POLL_MS = 20_000
SETTLING_POLL_MS = 120_000
SETTLING_WINDOW = timedelta(minutes=60)
MATCH_END_BUFFER = timedelta(minutes=20)
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


def _parse_fpl_time(value: str | None) -> datetime | None:
    if not value:
        return None

    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _format_fixture_time(kickoff_time: str | None) -> str:
    kickoff = _parse_fpl_time(kickoff_time)
    if kickoff is None:
        return "-"

    return kickoff.astimezone(FIXTURE_TIMEZONE).strftime("%a %H:%M")


def _fixture_finished(fixture: JsonObject) -> bool:
    return bool(fixture.get("finished") or fixture.get("finished_provisional"))


def _fixture_started(fixture: JsonObject) -> bool:
    return bool(fixture.get("started") or _fixture_finished(fixture))


def _estimated_fixture_end(fixture: JsonObject) -> datetime | None:
    if not _fixture_finished(fixture):
        return None

    kickoff = _parse_fpl_time(fixture.get("kickoff_time"))
    if kickoff is None:
        return None

    match_minutes = max(_stat_number(fixture.get("minutes")), 90)
    return kickoff + timedelta(minutes=match_minutes) + MATCH_END_BUFFER


def _refresh_policy(
    fixtures: Iterable[JsonObject], now: datetime | None = None
) -> JsonObject:
    fixtures = list(fixtures)
    now = now or datetime.now(timezone.utc)

    if any(
        _fixture_started(fixture) and not _fixture_finished(fixture)
        for fixture in fixtures
    ):
        return {
            "mode": "live",
            "pollMs": LIVE_POLL_MS,
            "reason": "match in play",
        }

    finished_at = [
        estimated_end
        for fixture in fixtures
        if (estimated_end := _estimated_fixture_end(fixture)) is not None
    ]
    last_finished_at = max(finished_at, default=None)
    if last_finished_at is not None and now - last_finished_at <= SETTLING_WINDOW:
        return {
            "mode": "settling",
            "pollMs": SETTLING_POLL_MS,
            "reason": "recently finished match",
            "lastMatchEndedAt": last_finished_at.isoformat(),
        }

    policy: JsonObject = {
        "mode": "frozen",
        "pollMs": None,
        "reason": "no recent live matches",
    }
    if last_finished_at is not None:
        policy["lastMatchEndedAt"] = last_finished_at.isoformat()
    return policy


def _select_gameweek(
    events: Iterable[JsonObject], gameweek_id: int | None = None
) -> JsonObject:
    events = list(events)
    if gameweek_id is not None:
        gameweek = next((event for event in events if event["id"] == gameweek_id), None)
        if gameweek is None:
            raise RuntimeError(f"Gameweek {gameweek_id} was not found")
        return gameweek

    gameweek = next((event for event in events if event["is_current"]), None)
    gameweek = gameweek or next(
        (event for event in reversed(events) if event["finished"]), None
    )
    gameweek = gameweek or next((event for event in events if event["is_next"]), None)

    if gameweek is None:
        raise RuntimeError("No FPL gameweek found")
    return gameweek


def _available_gameweeks(
    events: Iterable[JsonObject], current_gameweek_id: int
) -> list[JsonObject]:
    return [
        {"id": event["id"], "name": event["name"]}
        for event in sorted(events, key=lambda event: event["id"], reverse=True)
        if event["id"] <= current_gameweek_id
    ]


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


def _stat_number(value: Any) -> int:
    return (
        int(value)
        if isinstance(value, int | float) and not isinstance(value, bool)
        else 0
    )


def _fixture_player_stat(
    live_element: JsonObject, fixture_id: int | None, identifier: str
) -> int | None:
    if fixture_id is None:
        return None

    explanations = live_element.get("explain", [])
    for fixture in explanations:
        if fixture.get("fixture") != fixture_id:
            continue
        for item in fixture.get("stats", []):
            if item.get("identifier") == identifier:
                return _stat_number(item.get("value"))
        return 0

    return 0 if explanations else None


def _live_match_status(
    live_element: JsonObject, fixture: JsonObject | None
) -> str | None:
    if not fixture:
        return None
    return "Live"


def _build_player_context(
    elements: Iterable[JsonObject],
    teams: Iterable[JsonObject],
    fixtures: Iterable[JsonObject],
    live_elements: Iterable[JsonObject],
) -> tuple[dict[int, JsonObject], Callable[[int], JsonObject]]:
    teams = list(teams)
    team_codes = {team["id"]: team.get("code") for team in teams}
    players = {
        element["id"]: {
            "name": _player_name(element),
            "team": element.get("team"),
            "teamCode": element.get("team_code") or team_codes.get(element.get("team")),
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
        finished = _fixture_finished(fixture)
        started = _fixture_started(fixture)
        live = started and not finished
        fixtures_by_team[home_id].append(
            {
                "id": fixture.get("id"),
                "opponent": team_names.get(away_id, str(away_id)),
                "venue": "H",
                "started": started,
                "finished": finished,
                "live": live,
                "minutes": fixture.get("minutes"),
                "time": _format_fixture_time(fixture.get("kickoff_time")),
            }
        )
        fixtures_by_team[away_id].append(
            {
                "id": fixture.get("id"),
                "opponent": team_names.get(home_id, str(home_id)),
                "venue": "A",
                "started": started,
                "finished": finished,
                "live": live,
                "minutes": fixture.get("minutes"),
                "time": _format_fixture_time(fixture.get("kickoff_time")),
            }
        )

    def player_context(player_id: int) -> JsonObject:
        player = players.get(player_id, {})
        player_fixtures = fixtures_by_team.get(player.get("team"), [])
        if not player_fixtures:
            return {
                "opponent": "-",
                "fixtureTime": "-",
                "points": "-",
                "matchStatus": None,
                "isLive": False,
            }

        opponent = ", ".join(
            f'{fixture["opponent"]} ({fixture["venue"]})'
            for fixture in player_fixtures
        )
        live_fixture = next(
            (fixture for fixture in player_fixtures if fixture["live"]), None
        )
        fixture_time = (
            "Done"
            if any(fixture["finished"] for fixture in player_fixtures)
            else ", ".join(fixture["time"] for fixture in player_fixtures)
        )
        points = live_points.get(player_id, 0) if any(
            fixture["started"] for fixture in player_fixtures
        ) else "-"
        return {
            "opponent": opponent,
            "fixtureTime": fixture_time,
            "points": points,
            "matchStatus": _live_match_status(
                live_by_player.get(player_id, {}), live_fixture
            ),
            "isLive": live_fixture is not None,
        }

    return players, player_context, live_points


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
    elements: Iterable[JsonObject],
    teams: Iterable[JsonObject],
    fixtures: Iterable[JsonObject],
    live_elements: Iterable[JsonObject],
    entry_event_data: dict[int, JsonObject],
) -> list[JsonObject]:
    pairs = list(pairs)
    if not pairs:
        return []

    players, player_context, _ = _build_player_context(
        elements, teams, fixtures, live_elements
    )

    def picks_for_entry(entry_id: int) -> list[JsonObject]:
        return entry_event_data.get(entry_id, {}).get("picks", [])

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
            context = player_context(player_id)
            rows.append(
                {
                    "id": player_id,
                    "name": players.get(player_id, {}).get("name", f"Player {player_id}"),
                    "teamCode": players.get(player_id, {}).get("teamCode"),
                    "opponent": context["opponent"],
                    "fixtureTime": context["fixtureTime"],
                    "points": context["points"],
                    "matchStatus": context["matchStatus"],
                    "isLive": context["isLive"],
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

    players, player_context, _ = _build_player_context(
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
            context = player_context(player_id)
            multiplier = pick.get("multiplier", 0)
            picks.append(
                {
                    "id": player_id,
                    "name": player.get("name", f"Player {player_id}"),
                    "teamCode": player.get("teamCode"),
                    "opponent": context["opponent"],
                    "fixtureTime": context["fixtureTime"],
                    "points": context["points"],
                    "matchStatus": context["matchStatus"],
                    "isLive": context["isLive"],
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


def _apply_gameweek_status_counts(
    standings: Iterable[JsonObject],
    entry_event_data: dict[int, JsonObject],
    elements: Iterable[JsonObject],
    fixtures: Iterable[JsonObject],
) -> None:
    team_by_player = {element["id"]: element.get("team") for element in elements}
    fixtures_by_team: dict[int, list[JsonObject]] = defaultdict(list)
    for fixture in fixtures:
        fixtures_by_team[fixture["team_h"]].append(fixture)
        fixtures_by_team[fixture["team_a"]].append(fixture)

    def player_counts(player_id: int) -> tuple[int, int]:
        player_fixtures = fixtures_by_team.get(team_by_player.get(player_id), [])
        if not player_fixtures:
            return 0, 0

        has_started = any(_fixture_started(fixture) for fixture in player_fixtures)
        has_unfinished = any(
            not _fixture_finished(fixture) for fixture in player_fixtures
        )
        return int(has_started and has_unfinished), int(not has_started)

    counts_by_entry: dict[int, JsonObject] = {}
    for entry_id, event_data in entry_event_data.items():
        in_play = 0
        to_start = 0
        for pick in event_data.get("picks", []):
            if pick.get("multiplier", 0) <= 0:
                continue

            player_in_play, player_to_start = player_counts(pick["element"])
            in_play += player_in_play
            to_start += player_to_start

        counts_by_entry[entry_id] = {"inPlay": in_play, "toStart": to_start}

    for team in standings:
        counts = counts_by_entry.get(team["id"], {"inPlay": 0, "toStart": 0})
        team["inPlay"] = counts["inPlay"]
        team["toStart"] = counts["toStart"]


def _apply_live_gameweek_points(
    standings: Iterable[JsonObject],
    entry_event_data: dict[int, JsonObject],
    live_elements: Iterable[JsonObject],
) -> None:
    live_points = {
        element["id"]: element.get("stats", {}).get("total_points", 0)
        for element in live_elements
    }
    for team in standings:
        entry_id = team["id"]
        event_data = entry_event_data.get(entry_id, {})
        transfer_cost = event_data.get("entry_history", {}).get("event_transfers_cost", 0)
        live_sum = sum(
            live_points.get(pick["element"], 0) * pick.get("multiplier", 0)
            for pick in event_data.get("picks", [])
        )
        live_gw_points = live_sum - transfer_cost
        prev_gw = team["gameweekPoints"] if isinstance(team["gameweekPoints"], int | float) else 0
        team["gameweekPoints"] = live_gw_points
        if isinstance(team["totalPoints"], int | float):
            team["totalPoints"] = team["totalPoints"] - prev_gw + live_gw_points


def _format_standings(
    entries: Iterable[JsonObject],
    gameweek_id: int,
    badges: dict[int, str] | None = None,
    chips: dict[int, str] | None = None,
    entry_event_data: dict[int, JsonObject] | None = None,
) -> list[JsonObject]:
    badges = badges or {}
    chips = chips or {}
    entry_event_data = entry_event_data or {}
    should_rank_by_event = any(
        "total_points" in data.get("entry_history", {})
        for data in entry_event_data.values()
    )
    standings = []
    for entry in entries:
        is_ranked = "rank" in entry
        entry_id = entry["entry"]
        entry_history = entry_event_data.get(entry_id, {}).get("entry_history", {})
        gameweek_points = entry_history.get(
            "points", entry["event_total"] if is_ranked else "—"
        )
        total_points = entry_history.get(
            "total_points", entry["total"] if is_ranked else "—"
        )
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
                "gameweekPoints": gameweek_points,
                "totalPoints": total_points,
                "url": _team_url(entry["entry"], gameweek_id),
                "badgeUrl": badges.get(entry["entry"]),
                "headshotUrl": HEADSHOTS.get(entry["entry"]),
                "chip": chips.get(entry["entry"]),
            }
        )
    if should_rank_by_event:
        _sort_and_rank_standings(standings)
    return standings


def _sort_and_rank_standings(standings: list[JsonObject]) -> None:
    standings.sort(
        key=lambda team: (
            not isinstance(team["totalPoints"], int | float),
            -team["totalPoints"] if isinstance(team["totalPoints"], int | float) else 0,
            team["team"].casefold(),
        )
    )
    previous_total: int | float | None = None
    previous_rank: int | None = None
    for position, team in enumerate(standings, start=1):
        total = team["totalPoints"]
        if not isinstance(total, int | float):
            team["rank"] = "—"
        elif total == previous_total:
            team["rank"] = previous_rank
        else:
            team["rank"] = position
            previous_total = total
            previous_rank = position


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

        def combined_count(field: str) -> int:
            return sum(member.get(field, 0) for member in members)

        pairs.append(
            {
                "name": name,
                "members": members,
                "gameweekPoints": combined("gameweekPoints"),
                "totalPoints": combined("totalPoints"),
                "inPlay": combined_count("inPlay"),
                "toStart": combined_count("toStart"),
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
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _gameweek_snapshot_path(snapshot_dir: Path, gameweek_id: int) -> Path:
    return snapshot_dir / f"gw-{gameweek_id}.json"


def _read_gameweek_snapshot(snapshot_dir: Path, gameweek_id: int) -> JsonObject | None:
    try:
        data = json.loads(
            _gameweek_snapshot_path(snapshot_dir, gameweek_id).read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError):
        return None

    if data.get("gameweek", {}).get("id") != gameweek_id:
        return None
    return data


def _numeric_rank(value: Any) -> int | None:
    return value if isinstance(value, int) else None


def _rank_movement(current_rank: Any, previous_rank: Any) -> JsonObject | None:
    current = _numeric_rank(current_rank)
    previous = _numeric_rank(previous_rank)
    if current is None or previous is None:
        return None

    return {
        "direction": "same"
        if current == previous
        else "increase"
        if current < previous
        else "decrease",
        "previousRank": previous,
        "currentRank": current,
    }


def _apply_rank_movements(data: JsonObject, previous_snapshot: JsonObject | None) -> None:
    if previous_snapshot is None:
        return

    previous_team_ranks = {
        team["id"]: team.get("rank")
        for team in previous_snapshot.get("standings", [])
        if "id" in team
    }
    for team in data.get("standings", []):
        team.pop("rankMovement", None)
        movement = _rank_movement(team.get("rank"), previous_team_ranks.get(team.get("id")))
        if movement is not None:
            team["rankMovement"] = movement

    previous_pair_ranks = {
        pair["name"]: pair.get("rank")
        for pair in previous_snapshot.get("pairs", [])
        if "name" in pair
    }
    for pair in data.get("pairs", []):
        pair.pop("rankMovement", None)
        movement = _rank_movement(pair.get("rank"), previous_pair_ranks.get(pair.get("name")))
        if movement is not None:
            pair["rankMovement"] = movement


def _with_previous_rank_movements(data: JsonObject, snapshot_dir: Path | None) -> JsonObject:
    if snapshot_dir is None:
        return data

    gameweek_id = data.get("gameweek", {}).get("id")
    if not isinstance(gameweek_id, int) or gameweek_id <= 1:
        return data

    _apply_rank_movements(data, _read_gameweek_snapshot(snapshot_dir, gameweek_id - 1))
    return data


def _with_current_gameweek_metadata(
    data: JsonObject, current_gameweek: JsonObject, available_gameweeks: list[JsonObject]
) -> JsonObject:
    return {
        **data,
        "currentGameweek": {
            "id": current_gameweek["id"],
            "name": current_gameweek["name"],
        },
        "availableGameweeks": available_gameweeks,
    }


def _gameweek_is_locked(gameweek: JsonObject, current_gameweek: JsonObject) -> bool:
    return bool(gameweek.get("finished") or gameweek["id"] < current_gameweek["id"])


def _gameweek_fixtures_finished(fixtures: Iterable[JsonObject]) -> bool:
    fixtures = list(fixtures)
    return bool(fixtures) and all(_fixture_finished(fixture) for fixture in fixtures)


def _snapshot_finished_gameweek(
    data: JsonObject, fixtures: Iterable[JsonObject], snapshot_dir: Path | None
) -> None:
    if snapshot_dir is None:
        return

    if not _gameweek_fixtures_finished(fixtures):
        return

    gameweek_id = data.get("gameweek", {}).get("id")
    if not isinstance(gameweek_id, int):
        return

    try:
        _write_json(data, _gameweek_snapshot_path(snapshot_dir, gameweek_id))
    except OSError:
        pass


def fetch_standings(
    *,
    fetch_json: JsonFetcher | None = None,
    pairings: Iterable[tuple[str, tuple[int, int]]] = PAIRINGS,
    gameweek_id: int | None = None,
    snapshot_dir: Path | None = None,
    read_snapshot: bool = True,
) -> JsonObject:
    should_use_default_snapshot_dir = fetch_json is None and snapshot_dir is None
    fetch_json = fetch_json or _get_json
    if should_use_default_snapshot_dir:
        snapshot_dir = GAMEWEEK_SNAPSHOT_DIR

    bootstrap = fetch_json(f"{FPL_API_URL}/bootstrap-static/")
    current_gameweek = _select_gameweek(bootstrap["events"])
    gameweek = _select_gameweek(bootstrap["events"], gameweek_id)
    if gameweek["id"] > current_gameweek["id"]:
        raise RuntimeError(f"Gameweek {gameweek['id']} is not available yet")
    available_gameweeks = _available_gameweeks(
        bootstrap["events"], current_gameweek["id"]
    )
    if (
        read_snapshot
        and snapshot_dir is not None
        and _gameweek_is_locked(gameweek, current_gameweek)
    ):
        snapshot = _read_gameweek_snapshot(snapshot_dir, gameweek["id"])
        if snapshot is not None:
            return _with_previous_rank_movements(
                _with_current_gameweek_metadata(
                    snapshot, current_gameweek, available_gameweeks
                ),
                snapshot_dir,
            )

    league, entries = _fetch_league(fetch_json)
    badges = _fetch_badges(entries, fetch_json)
    entry_event_data = _fetch_entry_event_data(entries, gameweek["id"], fetch_json)
    transfer_data = _fetch_transfer_data(entries, fetch_json)
    chips = _format_chips(entry_event_data)
    standings = _format_standings(
        entries, gameweek["id"], badges, chips, entry_event_data
    )
    fixtures = (
        fetch_json(f"{FPL_API_URL}/fixtures/?event={gameweek['id']}")
        if standings
        else []
    )
    live = fetch_json(f"{FPL_API_URL}/event/{gameweek['id']}/live/") if standings else {}
    refresh_policy = _refresh_policy(fixtures)
    _apply_gameweek_status_counts(
        standings,
        entry_event_data,
        bootstrap["elements"],
        fixtures,
    )
    _apply_live_gameweek_points(standings, entry_event_data, live.get("elements", []))
    _sort_and_rank_standings(standings)
    pairs = _format_pairs(standings, pairings)
    duo_importance = _format_duo_importance(
        pairs,
        bootstrap["elements"],
        bootstrap.get("teams", []),
        fixtures,
        live.get("elements", []),
        entry_event_data,
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

    output = {
        "league": {"id": league["id"], "name": league["name"]},
        "gameweek": {"id": gameweek["id"], "name": gameweek["name"]},
        "currentGameweek": {
            "id": current_gameweek["id"],
            "name": current_gameweek["name"],
        },
        "availableGameweeks": available_gameweeks,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "teamCardImage": TEAM_CARD_IMAGE,
        "refreshPolicy": refresh_policy,
        "standings": standings,
        "pairs": pairs,
        "duoImportance": duo_importance,
        "teamDetails": team_details,
    }
    _with_previous_rank_movements(output, snapshot_dir)
    _snapshot_finished_gameweek(output, fixtures, snapshot_dir)
    return output


def update_standings(
    *,
    fetch_json: JsonFetcher | None = None,
    destination: Path | None = None,
    pairings: Iterable[tuple[str, tuple[int, int]]] = PAIRINGS,
    gameweek_id: int | None = None,
    snapshot_dir: Path | None = None,
) -> JsonObject:
    output = fetch_standings(
        fetch_json=fetch_json,
        pairings=pairings,
        gameweek_id=gameweek_id,
        snapshot_dir=snapshot_dir,
    )
    destination = destination or PUBLIC_DIR / "standings.json"
    _write_json(output, destination)
    return output
