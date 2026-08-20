import json
import tempfile
import unittest
from pathlib import Path

from services.fpl import (
    _format_pairs,
    _format_standings,
    _select_gameweek,
    update_standings,
)


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


class FormatPairsTests(unittest.TestCase):
    def setUp(self):
        self.teams = [
            {
                "id": 1,
                "team": "Alpha",
                "manager": "One",
                "gameweekPoints": 10,
                "totalPoints": 100,
            },
            {
                "id": 2,
                "team": "Beta",
                "manager": "Two",
                "gameweekPoints": 20,
                "totalPoints": 200,
            },
            {
                "id": 3,
                "team": "Mau",
                "manager": "Mau",
                "gameweekPoints": 12,
                "totalPoints": 120,
            },
        ]

    def test_combines_scores_and_ranks_pairs(self):
        pairs = _format_pairs(
            self.teams,
            (("Alpha & Beta", (1, 2)), ("Mau & Mau", (3, 3))),
        )

        self.assertEqual([pair["name"] for pair in pairs], ["Alpha & Beta", "Mau & Mau"])
        self.assertEqual([pair["rank"] for pair in pairs], [1, 2])
        self.assertEqual(pairs[0]["gameweekPoints"], 30)
        self.assertEqual(pairs[0]["totalPoints"], 300)
        self.assertEqual(pairs[1]["gameweekPoints"], 24)
        self.assertEqual(pairs[1]["totalPoints"], 240)
        self.assertEqual([member["id"] for member in pairs[1]["members"]], [3, 3])

    def test_rejects_a_missing_configured_team(self):
        with self.assertRaisesRegex(RuntimeError, "missing FPL entry 99"):
            _format_pairs(self.teams, (("Missing pair", (1, 99)),))


class UpdateStandingsTests(unittest.TestCase):
    def test_fetches_every_page_and_writes_the_result(self):
        requested_urls = []

        def fetch_json(url):
            requested_urls.append(url)
            if url.endswith("bootstrap-static/"):
                return {
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
                fetch_json=fetch_json, destination=destination, pairings=()
            )
            saved_output = json.loads(destination.read_text(encoding="utf-8"))

        self.assertEqual(len(requested_urls), 5)
        self.assertEqual([team["rank"] for team in output["standings"]], [1, 2])
        self.assertEqual(
            [team["badgeUrl"] for team in output["standings"]],
            ["https://example.com/10.png", "https://example.com/20.png"],
        )
        self.assertEqual(saved_output, output)

    def test_includes_ranked_and_new_entries(self):
        def fetch_json(url):
            if url.endswith("bootstrap-static/"):
                return {
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
