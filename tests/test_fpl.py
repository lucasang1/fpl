import json
import tempfile
import unittest
from pathlib import Path

from services.fpl import (
    _format_duo_importance,
    _format_pairs,
    _format_player_ownership,
    _format_point_details,
    _format_standings,
    _format_team_details,
    _fetch_chips,
    _select_gameweek,
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


class FormatPairsTests(unittest.TestCase):
    def setUp(self):
        self.teams = [
            {
                "id": 1,
                "team": "Alpha",
                "manager": "One",
                "gameweekPoints": 10,
                "totalPoints": 100,
                "chip": "BB",
            },
            {
                "id": 2,
                "team": "Beta",
                "manager": "Two",
                "gameweekPoints": 20,
                "totalPoints": 200,
                "chip": None,
            },
            {
                "id": 3,
                "team": "Mau",
                "manager": "Mau",
                "gameweekPoints": 12,
                "totalPoints": 120,
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
        self.assertEqual(pairs[1]["gameweekPoints"], 24)
        self.assertEqual(pairs[1]["totalPoints"], 240)
        self.assertEqual([member["id"] for member in pairs[1]["members"]], [3, 3])
        self.assertEqual([member["chip"] for member in pairs[0]["members"]], ["BB", None])
        self.assertEqual([member["chip"] for member in pairs[1]["members"]], ["TC", "TC"])

    def test_rejects_a_missing_configured_team(self):
        with self.assertRaisesRegex(RuntimeError, "missing FPL entry 99"):
            _format_pairs(self.teams, (("Missing pair", (1, 99)),))


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
                "team_h": 1,
                "team_a": 2,
                "started": True,
                "finished": False,
                "kickoff_time": "2024-08-18T07:00:00Z",
            }
        ]
        live_elements = [
            {"id": 10, "stats": {"total_points": 2}},
            {"id": 11, "stats": {"total_points": 3}},
            {"id": 20, "stats": {"total_points": 6}},
            {"id": 30, "stats": {"total_points": 5}},
            {"id": 40, "stats": {"total_points": 4}},
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
                return []

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
            output = update_standings(
                fetch_json=fetch_json,
                destination=destination,
                pairings=(("Test pair", (10, 20)),),
            )
            saved_output = json.loads(destination.read_text(encoding="utf-8"))

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
