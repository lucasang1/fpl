import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from services.fpl import (
    _apply_gameweek_status_counts,
    _format_duo_importance,
    _format_pairs,
    _format_player_ownership,
    _format_point_details,
    _format_standings,
    _format_team_details,
    _fetch_chips,
    _refresh_policy,
    _select_gameweek,
    fetch_standings,
    update_standings,
)


class FormatPointDetailsTests(unittest.TestCase):
    def test_formats_explained_points_and_zero_defensive_progress(self):
        live_element = {
            "stats": {
                "played": True,
                "defensive_contribution": 5,
                "bps": 37,
                "total_points": 11,
            },
            "explain": [
                {
                    "fixture": 1,
                    "stats": [
                        {"identifier": "minutes", "value": 90, "points": 2},
                        {"identifier": "assists", "value": 1, "points": 3},
                        {"identifier": "clean_sheets", "value": 1, "points": 4},
                        {"identifier": "bonus", "value": 2, "points": 2},
                    ],
                }
            ],
        }

        self.assertEqual(
            _format_point_details(live_element, 2),
            {
                "rows": [
                    {"identifier": "assists", "value": 1, "points": 3},
                    {
                        "identifier": "defensive_contribution",
                        "value": 5,
                        "points": 0,
                    },
                    {"identifier": "clean_sheets", "value": 1, "points": 4},
                    {"identifier": "minutes", "value": 90, "points": 2},
                    {"identifier": "bonus", "value": 2, "points": 2, "bps": 37},
                ],
                "total": 11,
            },
        )

    def test_hides_details_until_player_has_played(self):
        self.assertIsNone(_format_point_details({"stats": {"played": False}}, 3))


class SelectGameweekTests(unittest.TestCase):
    def test_prefers_current_gameweek(self):
        events = [
            {"id": 1, "is_current": False, "finished": True, "is_next": False},
            {"id": 2, "is_current": True, "finished": False, "is_next": False},
            {"id": 3, "is_current": False, "finished": False, "is_next": True},
        ]

        self.assertEqual(_select_gameweek(events)["id"], 2)

    def test_uses_latest_finished_gameweek_when_none_is_current(self):
        events = [
            {"id": 1, "is_current": False, "finished": True, "is_next": False},
            {"id": 2, "is_current": False, "finished": True, "is_next": False},
            {"id": 3, "is_current": False, "finished": False, "is_next": True},
        ]

        self.assertEqual(_select_gameweek(events)["id"], 2)

    def test_rejects_an_empty_schedule(self):
        with self.assertRaisesRegex(RuntimeError, "No FPL gameweek found"):
            _select_gameweek([])


class FormatStandingsTests(unittest.TestCase):
    def test_formats_unranked_new_entries(self):
        entries = [
            {
                "entry": 42,
                "entry_name": "New team",
                "player_first_name": "Ada",
                "player_last_name": "Lovelace",
            }
        ]

        self.assertEqual(
            _format_standings(entries, 3),
            [
                {
                    "id": 42,
                    "rank": "—",
                    "team": "New team",
                    "manager": "Ada Lovelace",
                    "gameweekPoints": "—",
                    "totalPoints": "—",
                    "url": "https://fantasy.premierleague.com/entry/42/event/3",
                    "badgeUrl": None,
                    "headshotUrl": None,
                    "chip": None,
                }
            ],
        )

    def test_includes_team_badge(self):
        entries = [
            {
                "entry": 42,
                "entry_name": "Badged team",
                "player_first_name": "Ada",
                "player_last_name": "Lovelace",
            }
        ]

        standings = _format_standings(entries, 3, {42: "https://example.com/badge.png"})

        self.assertEqual(standings[0]["badgeUrl"], "https://example.com/badge.png")

    def test_includes_configured_manager_headshot(self):
        entries = [
            {
                "entry": 2020069,
                "entry_name": "Headshot team",
                "player_first_name": "Lucas",
                "player_last_name": "Manager",
            }
        ]

        standings = _format_standings(entries, 3)

        self.assertEqual(standings[0]["headshotUrl"], "/headshots/lucas.png")

    def test_includes_chip_label(self):
        entries = [
            {
                "entry": 42,
                "entry_name": "Triple team",
                "player_first_name": "Ada",
                "player_last_name": "Lovelace",
            }
        ]

        standings = _format_standings(entries, 3, chips={42: "TC"})

        self.assertEqual(standings[0]["chip"], "TC")

    def test_uses_entry_history_for_selected_gameweek_scores_and_ranks(self):
        entries = [
            {
                "rank": 1,
                "entry": 1,
                "entry_name": "Current leader",
                "player_name": "Leader Manager",
                "event_total": 99,
                "total": 199,
            },
            {
                "rank": 2,
                "entry": 2,
                "entry_name": "GW1 leader",
                "player_name": "Past Manager",
                "event_total": 1,
                "total": 100,
            },
        ]
        entry_event_data = {
            1: {"entry_history": {"points": 10, "total_points": 10}},
            2: {"entry_history": {"points": 20, "total_points": 20}},
        }

        standings = _format_standings(
            entries, 1, entry_event_data=entry_event_data
        )

        self.assertEqual(
            [
                (
                    team["rank"],
                    team["team"],
                    team["gameweekPoints"],
                    team["totalPoints"],
                )
                for team in standings
            ],
            [(1, "GW1 leader", 20, 20), (2, "Current leader", 10, 10)],
        )


class FetchChipsTests(unittest.TestCase):
    def test_maps_active_chips_to_short_labels(self):
        entries = [{"entry": 1}, {"entry": 2}, {"entry": 3}, {"entry": 4}, {"entry": 5}]
        chips_by_entry = {
            1: "bboost",
            2: "3xc",
            3: "freehit",
            4: "wildcard",
            5: None,
        }

        def fetch_json(url):
            entry_id = int(url.split("/entry/", 1)[1].split("/", 1)[0])
            return {"active_chip": chips_by_entry[entry_id]}

        self.assertEqual(
            _fetch_chips(entries, 6, fetch_json),
            {1: "BB", 2: "TC", 3: "FH", 4: "WC"},
        )


class RefreshPolicyTests(unittest.TestCase):
    def test_live_fixture_polls_every_twenty_seconds(self):
        policy = _refresh_policy(
            [
                {
                    "started": True,
                    "finished": False,
                    "finished_provisional": False,
                    "kickoff_time": "2024-08-18T07:00:00Z",
                }
            ],
            now=datetime(2024, 8, 18, 8, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(policy["mode"], "live")
        self.assertEqual(policy["pollMs"], 20_000)

    def test_recently_finished_fixture_polls_every_two_minutes(self):
        policy = _refresh_policy(
            [
                {
                    "started": True,
                    "finished": True,
                    "minutes": 90,
                    "kickoff_time": "2024-08-18T07:00:00Z",
                }
            ],
            now=datetime(2024, 8, 18, 8, 55, tzinfo=timezone.utc),
        )

        self.assertEqual(policy["mode"], "settling")
        self.assertEqual(policy["pollMs"], 120_000)
        self.assertEqual(policy["lastMatchEndedAt"], "2024-08-18T08:50:00+00:00")

    def test_old_finished_fixture_stops_auto_polling(self):
        policy = _refresh_policy(
            [
                {
                    "started": True,
                    "finished": True,
                    "minutes": 90,
                    "kickoff_time": "2024-08-18T07:00:00Z",
                }
            ],
            now=datetime(2024, 8, 18, 10, 0, tzinfo=timezone.utc),
        )

        self.assertEqual(policy["mode"], "frozen")
        self.assertIsNone(policy["pollMs"])


class FormatPairsTests(unittest.TestCase):
    def setUp(self):
        self.teams = [
            {
                "id": 1,
                "team": "Alpha",
                "manager": "One",
                "gameweekPoints": 10,
                "totalPoints": 100,
                "inPlay": 2,
                "toStart": 1,
                "chip": "BB",
            },
            {
                "id": 2,
                "team": "Beta",
                "manager": "Two",
                "gameweekPoints": 20,
                "totalPoints": 200,
                "inPlay": 3,
                "toStart": 4,
                "chip": None,
            },
            {
                "id": 3,
                "team": "Mau",
                "manager": "Mau",
                "gameweekPoints": 12,
                "totalPoints": 120,
                "inPlay": 0,
                "toStart": 5,
                "chip": "TC",
            },
        ]

    def test_combines_points_and_ranks_pairs(self):
        pairs = _format_pairs(
            self.teams,
            (("Alpha & Beta", (1, 2)), ("Mau", (3, 3))),
        )

        self.assertEqual([pair["name"] for pair in pairs], ["Alpha & Beta", "Mau"])
        self.assertEqual([pair["rank"] for pair in pairs], [1, 2])
        self.assertEqual(pairs[0]["gameweekPoints"], 30)
        self.assertEqual(pairs[0]["totalPoints"], 300)
        self.assertEqual(pairs[0]["inPlay"], 5)
        self.assertEqual(pairs[0]["toStart"], 5)
        self.assertEqual(pairs[1]["gameweekPoints"], 24)
        self.assertEqual(pairs[1]["totalPoints"], 240)
        self.assertEqual(pairs[1]["inPlay"], 0)
        self.assertEqual(pairs[1]["toStart"], 10)
        self.assertEqual([member["id"] for member in pairs[1]["members"]], [3, 3])
        self.assertEqual([member["chip"] for member in pairs[0]["members"]], ["BB", None])
        self.assertEqual([member["chip"] for member in pairs[1]["members"]], ["TC", "TC"])

    def test_rejects_a_missing_configured_team(self):
        with self.assertRaisesRegex(RuntimeError, "missing FPL entry 99"):
            _format_pairs(self.teams, (("Missing pair", (1, 99)),))


class GameweekStatusCountTests(unittest.TestCase):
    def test_counts_double_gameweek_player_in_play_until_all_fixtures_finish(self):
        standings = [{"id": 1}, {"id": 2}]
        entry_event_data = {
            1: {
                "picks": [
                    {"element": 10, "multiplier": 1},
                    {"element": 20, "multiplier": 1},
                    {"element": 30, "multiplier": 1},
                    {"element": 40, "multiplier": 0},
                ],
            },
            2: {"picks": [{"element": 40, "multiplier": 1}]},
        }
        elements = [
            {"id": 10, "team": 1},
            {"id": 20, "team": 2},
            {"id": 30, "team": 3},
            {"id": 40, "team": 1},
        ]
        fixtures = [
            {"team_h": 1, "team_a": 9, "started": True, "finished": True},
            {"team_h": 1, "team_a": 10, "started": False, "finished": False},
            {"team_h": 2, "team_a": 11, "started": False, "finished": False},
            {"team_h": 3, "team_a": 12, "started": True, "finished": True},
        ]

        _apply_gameweek_status_counts(
            standings,
            entry_event_data,
            elements,
            fixtures,
        )

        self.assertEqual(standings[0]["inPlay"], 1)
        self.assertEqual(standings[0]["toStart"], 1)
        self.assertEqual(standings[1]["inPlay"], 1)
        self.assertEqual(standings[1]["toStart"], 0)


class FormatPlayerOwnershipTests(unittest.TestCase):
    def test_counts_raw_and_effective_ownership(self):
        entries = [{"entry": 1}, {"entry": 2}]
        elements = [
            {"id": 10, "web_name": "Salah"},
            {"id": 20, "web_name": "Haaland"},
            {"id": 30, "web_name": "Saka"},
        ]

        def fetch_json(url):
            entry_id = int(url.split("/entry/", 1)[1].split("/", 1)[0])
            picks_by_entry = {
                1: [
                    {"element": 10, "multiplier": 2},
                    {"element": 20, "multiplier": 1},
                    {"element": 30, "multiplier": 0},
                ],
                2: [
                    {"element": 10, "multiplier": 1},
                    {"element": 20, "multiplier": 3},
                ],
            }
            return {"picks": picks_by_entry[entry_id]}

        ownership = _format_player_ownership(entries, 4, elements, fetch_json)

        self.assertEqual(
            ownership,
            [
                {
                    "id": 20,
                    "name": "Haaland",
                    "ownership": 100.0,
                    "effectiveOwnership": 200.0,
                },
                {
                    "id": 10,
                    "name": "Salah",
                    "ownership": 100.0,
                    "effectiveOwnership": 150.0,
                },
                {
                    "id": 30,
                    "name": "Saka",
                    "ownership": 50.0,
                    "effectiveOwnership": 0.0,
                },
            ],
        )


class FormatDuoImportanceTests(unittest.TestCase):
    def test_compares_selected_duo_exposure_against_other_duos(self):
        pairs = [
            {
                "name": "Alpha & Beta",
                "members": [{"id": 1}, {"id": 2}],
            },
            {
                "name": "Gamma & Delta",
                "members": [{"id": 3}, {"id": 4}],
            },
            {
                "name": "Echo & Foxtrot",
                "members": [{"id": 5}, {"id": 6}],
            },
        ]
        elements = [
            {"id": 10, "web_name": "Salah", "team": 20},
            {"id": 30, "web_name": "Verbruggen", "team": 10},
        ]
        teams = [
            {"id": 10, "short_name": "BHA", "code": 36},
            {"id": 20, "short_name": "LIV", "code": 14},
            {"id": 30, "short_name": "AVL", "code": 7},
            {"id": 40, "short_name": "MUN", "code": 1},
        ]
        fixtures = [
            {
                "team_h": 10,
                "team_a": 30,
                "started": True,
                "finished": True,
                "kickoff_time": "2024-08-18T07:00:00Z",
            },
            {
                "team_h": 20,
                "team_a": 40,
                "started": False,
                "finished": False,
                "kickoff_time": "2024-08-19T19:00:00Z",
            },
        ]
        live_elements = [
            {"id": 10, "stats": {"total_points": 0}},
            {"id": 30, "stats": {"total_points": 6}},
        ]
        picks_by_entry = {
            1: [{"element": 10, "multiplier": 2}, {"element": 30, "multiplier": 1}],
            2: [{"element": 10, "multiplier": 1}],
            3: [{"element": 10, "multiplier": 1}, {"element": 30, "multiplier": 1}],
            4: [],
            5: [{"element": 10, "multiplier": 0}],
            6: [],
        }

        entry_event_data = {
            entry_id: {"picks": picks}
            for entry_id, picks in picks_by_entry.items()
        }

        importance = _format_duo_importance(
            pairs, elements, teams, fixtures, live_elements, entry_event_data
        )

        alpha = importance[0]["players"]
        self.assertEqual(alpha[0]["name"], "Salah")
        self.assertEqual(alpha[0]["teamCode"], 14)
        self.assertEqual(alpha[0]["opponent"], "MUN (H)")
        self.assertEqual(alpha[0]["fixtureTime"], "Tue 03:00")
        self.assertEqual(alpha[0]["points"], "-")
        self.assertEqual(alpha[0]["importance"], 250.0)
        self.assertEqual(
            alpha[0]["teams"],
            {
                "started": [
                    {"name": "Team 1", "captain": True},
                    {"name": "Team 2", "captain": False},
                    {"name": "Team 3", "captain": False},
                ],
                "benched": [{"name": "Team 5"}],
            },
        )
        self.assertEqual(alpha[1]["name"], "Verbruggen")
        self.assertEqual(alpha[1]["opponent"], "AVL (H)")
        self.assertEqual(alpha[1]["fixtureTime"], "Done")
        self.assertEqual(alpha[1]["points"], 6)
        self.assertEqual(alpha[1]["importance"], 50.0)
        self.assertEqual(
            alpha[1]["teams"],
            {
                "started": [
                    {"name": "Team 1", "captain": False},
                    {"name": "Team 3", "captain": False},
                ],
                "benched": [],
            },
        )


class FormatTeamDetailsTests(unittest.TestCase):
    def test_formats_team_metadata_and_players_by_position(self):
        standings = [
            {
                "id": 1,
                "team": "Alpha",
                "manager": "One",
                "gameweekPoints": 45,
                "totalPoints": 420,
            },
            {
                "id": 2,
                "team": "Beta",
                "manager": "Two",
                "gameweekPoints": 40,
                "totalPoints": 400,
            },
        ]
        entry_event_data = {
            1: {
                "active_chip": "wildcard",
                "entry_history": {
                    "event_transfers": 2,
                    "event_transfers_cost": 4,
                    "value": 1013,
                    "bank": 7,
                },
                "picks": [
                    {
                        "element": 30,
                        "position": 8,
                        "multiplier": 1,
                        "is_captain": False,
                        "is_vice_captain": False,
                    },
                    {
                        "element": 40,
                        "position": 11,
                        "multiplier": 1,
                        "is_captain": False,
                        "is_vice_captain": False,
                    },
                    {
                        "element": 10,
                        "position": 1,
                        "multiplier": 1,
                        "is_captain": False,
                        "is_vice_captain": False,
                    },
                    {
                        "element": 20,
                        "position": 4,
                        "multiplier": 2,
                        "is_captain": True,
                        "is_vice_captain": False,
                    },
                    {
                        "element": 11,
                        "position": 12,
                        "multiplier": 0,
                        "is_captain": False,
                        "is_vice_captain": True,
                    },
                    {
                        "element": 31,
                        "position": 13,
                        "multiplier": 0,
                        "is_captain": False,
                        "is_vice_captain": False,
                    },
                    {
                        "element": 41,
                        "position": 14,
                        "multiplier": 0,
                        "is_captain": False,
                        "is_vice_captain": False,
                    },
                    {
                        "element": 21,
                        "position": 15,
                        "multiplier": 0,
                        "is_captain": False,
                        "is_vice_captain": False,
                    },
                ],
            },
            2: {
                "active_chip": None,
                "entry_history": {"event_transfers": 0, "value": 1000, "bank": 0},
                "picks": [
                    {"element": 10, "position": 1, "multiplier": 1},
                    {"element": 20, "position": 4, "multiplier": 1},
                    {"element": 30, "position": 8, "multiplier": 1},
                ],
            },
        }
        elements = [
            {"id": 10, "web_name": "Raya", "team": 1, "element_type": 1},
            {"id": 11, "web_name": "Flekken", "team": 2, "element_type": 1},
            {"id": 20, "web_name": "Gabriel", "team": 1, "element_type": 2},
            {"id": 21, "web_name": "White", "team": 1, "element_type": 2},
            {"id": 30, "web_name": "Saka", "team": 1, "element_type": 3},
            {"id": 31, "web_name": "Palmer", "team": 1, "element_type": 3},
            {"id": 40, "web_name": "Watkins", "team": 2, "element_type": 4},
            {"id": 41, "web_name": "Haaland", "team": 2, "element_type": 4},
        ]
        teams = [
            {"id": 1, "short_name": "ARS", "code": 3},
            {"id": 2, "short_name": "BRE", "code": 94},
        ]
        fixtures = [
            {
                "id": 100,
                "team_h": 1,
                "team_a": 2,
                "started": True,
                "finished": False,
                "minutes": 60,
                "kickoff_time": "2024-08-18T07:00:00Z",
            }
        ]
        live_elements = [
            {"id": 10, "stats": {"total_points": 2, "minutes": 60, "starts": 1}},
            {"id": 11, "stats": {"total_points": 3, "minutes": 0, "starts": 0}},
            {"id": 20, "stats": {"total_points": 6, "minutes": 45, "starts": 1}},
            {"id": 30, "stats": {"total_points": 5, "minutes": 60, "starts": 0}},
            {"id": 40, "stats": {"total_points": 4, "minutes": 30, "starts": 0}},
        ]

        details = _format_team_details(
            standings,
            entry_event_data,
            {
                1: [
                    {
                        "event": 1,
                        "element_in": 30,
                        "element_out": 31,
                        "time": "2024-08-17T11:00:00Z",
                    },
                    {
                        "event": 1,
                        "element_in": 40,
                        "element_out": 41,
                        "time": "2024-08-17T12:00:00Z",
                    },
                ],
                2: [],
            },
            1,
            elements,
            teams,
            fixtures,
            live_elements,
        )

        self.assertEqual(details[0]["team"], "Alpha")
        self.assertEqual(details[0]["transfersMade"], 2)
        self.assertEqual(details[0]["transferCost"], 4)
        self.assertEqual(
            details[0]["transfers"],
            [
                {"in": "Saka", "out": "Palmer", "time": "2024-08-17T11:00:00Z"},
                {"in": "Watkins", "out": "Haaland", "time": "2024-08-17T12:00:00Z"},
            ],
        )
        self.assertEqual(details[0]["chip"], "WC")
        self.assertEqual(details[0]["teamValue"], 101.3)
        self.assertEqual(details[0]["bank"], 0.7)
        self.assertEqual(details[1]["transferCost"], 0)
        self.assertEqual(
            [player["name"] for player in details[0]["players"]],
            [
                "Raya",
                "Gabriel",
                "Saka",
                "Watkins",
                "Flekken",
                "White",
                "Palmer",
                "Haaland",
            ],
        )
        self.assertTrue(details[0]["players"][4]["isBenched"])
        self.assertEqual(details[0]["players"][0]["teamCode"], 3)
        self.assertTrue(details[0]["players"][1]["isCaptain"])
        self.assertEqual(details[0]["players"][1]["importance"], 100.0)
        self.assertEqual(
            details[0]["players"][1]["teams"],
            {
                "started": [
                    {"name": "Alpha", "captain": True},
                    {"name": "Beta", "captain": False},
                ],
                "benched": [],
            },
        )
        self.assertEqual(details[0]["players"][2]["opponent"], "BRE (H)")
        self.assertEqual(details[0]["players"][2]["fixtureTime"], "Sun 15:00")
        self.assertEqual(details[0]["players"][2]["points"], 5)
        self.assertEqual(
            {player["name"]: player["matchStatus"] for player in details[0]["players"]},
            {
                "Raya": "In Play",
                "Gabriel": "Subbed Off",
                "Saka": "Subbed On",
                "Watkins": "Subbed Off",
                "Flekken": "Not In Play",
                "White": "Not In Play",
                "Palmer": "Not In Play",
                "Haaland": "Not In Play",
            },
        )
        self.assertTrue(all(player["isLive"] for player in details[0]["players"]))


class UpdateStandingsTests(unittest.TestCase):
    def test_fetches_every_page_and_writes_the_result(self):
        requested_urls = []

        def fetch_json(url):
            requested_urls.append(url)
            if url.endswith("bootstrap-static/"):
                return {
                    "elements": [
                        {"id": 1, "web_name": "Player One"},
                        {"id": 2, "web_name": "Player Two"},
                    ],
                    "events": [
                        {
                            "id": 7,
                            "name": "Gameweek 7",
                            "is_current": True,
                            "finished": False,
                            "is_next": False,
                        }
                    ]
                }

            if url.endswith("/picks/"):
                return {
                    "active_chip": None,
                    "entry_history": {"event_transfers": 0, "value": 1000},
                    "picks": [
                        {"element": 1, "multiplier": 1},
                        {"element": 2, "multiplier": 2},
                    ]
                }

            if url.endswith("/transfers/"):
                return []

            if "/fixtures/" in url:
                return [
                    {
                        "team_h": 1,
                        "team_a": 2,
                        "started": True,
                        "finished": True,
                        "kickoff_time": "2024-08-18T07:00:00Z",
                    }
                ]

            if "/live/" in url:
                return {"elements": []}

            if "/entry/" in url:
                entry_id = int(url.rstrip("/").rsplit("/", 1)[1])
                return {"club_badge_src": f"https://example.com/{entry_id}.png"}

            page = int(url.rsplit("=", 1)[1])
            entry = {
                "rank": page,
                "entry": page * 10,
                "entry_name": f"Team {page}",
                "player_name": f"Manager {page}",
                "event_total": page * 5,
                "total": page * 100,
            }
            return {
                "league": {"id": 123, "name": "Test League"},
                "new_entries": {"results": []},
                "standings": {"results": [entry], "has_next": page == 1},
            }

        with tempfile.TemporaryDirectory() as temporary_directory:
            destination = Path(temporary_directory) / "standings.json"
            snapshot_dir = Path(temporary_directory) / "snapshots"
            output = update_standings(
                fetch_json=fetch_json,
                destination=destination,
                pairings=(("Test pair", (10, 20)),),
                snapshot_dir=snapshot_dir,
            )
            saved_output = json.loads(destination.read_text(encoding="utf-8"))
            saved_snapshot = json.loads(
                (snapshot_dir / "gw-7.json").read_text(encoding="utf-8")
            )

        self.assertEqual(len(requested_urls), 11)
        self.assertEqual(
            len([url for url in requested_urls if url.endswith("/picks/")]),
            2,
        )
        self.assertEqual(output["teamCardImage"], "badge")
        self.assertEqual([team["rank"] for team in output["standings"]], [1, 2])
        self.assertEqual(
            [team["badgeUrl"] for team in output["standings"]],
            ["https://example.com/10.png", "https://example.com/20.png"],
        )
        self.assertEqual(
            [pair["name"] for pair in output["duoImportance"]],
            ["Test pair"],
        )
        self.assertEqual([team["team"] for team in output["teamDetails"]], ["Team 1", "Team 2"])
        self.assertEqual(saved_output, output)
        self.assertEqual(saved_snapshot, output)

    def test_does_not_snapshot_until_all_gameweek_fixtures_finish(self):
        def fetch_json(url):
            if url.endswith("bootstrap-static/"):
                return {
                    "elements": [{"id": 1, "web_name": "Player One", "team": 1}],
                    "teams": [
                        {"id": 1, "short_name": "ARS"},
                        {"id": 2, "short_name": "BRE"},
                        {"id": 3, "short_name": "CHE"},
                    ],
                    "events": [
                        {
                            "id": 7,
                            "name": "Gameweek 7",
                            "is_current": True,
                            "finished": False,
                            "is_next": False,
                        }
                    ]
                }

            if url.endswith("/picks/"):
                return {
                    "active_chip": None,
                    "entry_history": {
                        "points": 12,
                        "total_points": 100,
                        "event_transfers": 0,
                        "value": 1000,
                    },
                    "picks": [{"element": 1, "multiplier": 1}],
                }

            if url.endswith("/transfers/"):
                return []

            if "/fixtures/" in url:
                return [
                    {
                        "team_h": 1,
                        "team_a": 2,
                        "started": True,
                        "finished": True,
                        "kickoff_time": "2024-08-16T11:00:00Z",
                    },
                    {
                        "team_h": 3,
                        "team_a": 2,
                        "started": False,
                        "finished": False,
                        "kickoff_time": "2024-08-18T11:00:00Z",
                    },
                ]

            if "/live/" in url:
                return {"elements": []}

            if "/entry/" in url:
                return {"club_badge_src": None}

            return {
                "league": {"id": 123, "name": "Test League"},
                "new_entries": {"results": []},
                "standings": {
                    "results": [
                        {
                            "rank": 1,
                            "entry": 10,
                            "entry_name": "Team 1",
                            "player_name": "Manager 1",
                            "event_total": 12,
                            "total": 100,
                        }
                    ],
                    "has_next": False,
                },
            }

        with tempfile.TemporaryDirectory() as temporary_directory:
            snapshot_dir = Path(temporary_directory) / "snapshots"
            output = update_standings(
                fetch_json=fetch_json,
                destination=Path(temporary_directory) / "standings.json",
                pairings=(),
                snapshot_dir=snapshot_dir,
            )

        self.assertEqual(output["refreshPolicy"]["mode"], "frozen")
        self.assertFalse((snapshot_dir / "gw-7.json").exists())

    def test_uses_saved_snapshot_for_locked_gameweek(self):
        requested_urls = []
        snapshot = {
            "league": {"id": 123, "name": "Test League"},
            "gameweek": {"id": 1, "name": "Gameweek 1"},
            "currentGameweek": {"id": 1, "name": "Gameweek 1"},
            "availableGameweeks": [{"id": 1, "name": "Gameweek 1"}],
            "updatedAt": "2024-08-20T00:00:00+00:00",
            "teamCardImage": "badge",
            "refreshPolicy": {"mode": "frozen", "pollMs": None},
            "standings": [{"id": 10, "team": "Saved team", "gameweekPoints": 42}],
            "pairs": [],
            "duoImportance": [],
            "teamDetails": [],
        }

        def fetch_json(url):
            requested_urls.append(url)
            if url.endswith("bootstrap-static/"):
                return {
                    "events": [
                        {
                            "id": 1,
                            "name": "Gameweek 1",
                            "is_current": False,
                            "finished": True,
                            "is_next": False,
                        },
                        {
                            "id": 2,
                            "name": "Gameweek 2",
                            "is_current": True,
                            "finished": False,
                            "is_next": False,
                        },
                    ],
                }
            self.fail(f"Unexpected network fetch after snapshot hit: {url}")

        with tempfile.TemporaryDirectory() as temporary_directory:
            snapshot_dir = Path(temporary_directory) / "snapshots"
            snapshot_dir.mkdir()
            (snapshot_dir / "gw-1.json").write_text(
                json.dumps(snapshot), encoding="utf-8"
            )

            output = fetch_standings(
                fetch_json=fetch_json,
                pairings=(),
                gameweek_id=1,
                snapshot_dir=snapshot_dir,
            )

        self.assertEqual(len(requested_urls), 1)
        self.assertEqual(output["standings"], snapshot["standings"])
        self.assertEqual(output["currentGameweek"], {"id": 2, "name": "Gameweek 2"})
        self.assertEqual(
            output["availableGameweeks"],
            [
                {"id": 2, "name": "Gameweek 2"},
                {"id": 1, "name": "Gameweek 1"},
            ],
        )

    def test_includes_ranked_and_new_entries(self):
        def fetch_json(url):
            if url.endswith("bootstrap-static/"):
                return {
                    "elements": [{"id": 1, "web_name": "Player One"}],
                    "events": [
                        {
                            "id": 1,
                            "name": "Gameweek 1",
                            "is_current": True,
                            "finished": False,
                            "is_next": False,
                        }
                    ]
                }

            if url.endswith("/picks/"):
                return {
                    "active_chip": None,
                    "entry_history": {"event_transfers": 0, "value": 1000},
                    "picks": [{"element": 1, "multiplier": 1}],
                }

            if url.endswith("/transfers/"):
                return []

            if "/fixtures/" in url:
                return []

            if "/live/" in url:
                return {"elements": []}

            if "/entry/" in url:
                return {"club_badge_src": None}

            return {
                "league": {"id": 123, "name": "Test League"},
                "new_entries": {
                    "results": [
                        {
                            "entry": 2,
                            "entry_name": "New team",
                            "player_first_name": "New",
                            "player_last_name": "Manager",
                        }
                    ]
                },
                "standings": {
                    "results": [
                        {
                            "rank": 1,
                            "entry": 1,
                            "entry_name": "Ranked team",
                            "player_name": "Ranked Manager",
                            "event_total": 10,
                            "total": 10,
                        }
                    ],
                    "has_next": False,
                },
            }

        with tempfile.TemporaryDirectory() as temporary_directory:
            output = update_standings(
                fetch_json=fetch_json,
                destination=Path(temporary_directory) / "standings.json",
                pairings=(),
            )

        self.assertEqual(
            [team["team"] for team in output["standings"]],
            ["Ranked team", "New team"],
        )


if __name__ == "__main__":
    unittest.main()
