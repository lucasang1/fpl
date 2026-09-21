import io
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from telegram_report import (
    _data_is_ready,
    _pack_messages,
    _report_key,
    _send_message,
    _target_event,
    _transfer_data_is_ready,
    build_report_blocks,
    run,
)


EVENT = {
    "id": 6,
    "name": "Gameweek 6",
    "deadline_time": "2026-09-26T10:00:00Z",
}


def sample_data():
    return {
        "gameweek": {"id": 6, "name": "Gameweek 6"},
        "standings": [
            {"id": 1, "team": "maubeefcherkii"},
            {"id": 2, "team": "Forte Ding"},
            {"id": 3, "team": "joshur10"},
        ],
        "teamDetails": [
            {
                "id": 1,
                "team": "maubeefcherkii",
                "chip": None,
                "transferCost": 0,
                "transfers": [{"out": "Dedić", "in": "Hall"}],
                "players": [
                    {
                        "id": player_id,
                        "name": "Haaland" if player_id == 1 else f"P{player_id}",
                        "isCaptain": player_id == 1,
                    }
                    for player_id in range(1, 16)
                ],
            },
            {
                "id": 2,
                "team": "Forte Ding",
                "chip": "TC",
                "transferCost": 4,
                "transfers": [
                    {"out": "Palmer", "in": "Saka"},
                    {"out": "Watkins", "in": "Haaland"},
                ],
                "players": [
                    {
                        "id": player_id,
                        "name": "Salah" if player_id == 16 else f"P{player_id}",
                        "isCaptain": player_id == 16,
                    }
                    for player_id in range(16, 31)
                ],
            },
            {
                "id": 3,
                "team": "joshur10",
                "chip": "WC",
                "transferCost": 0,
                "transfers": [],
                "players": [
                    {
                        "id": player_id,
                        "name": f"P{player_id}",
                        "isCaptain": player_id == 31,
                    }
                    for player_id in range(31, 46)
                ],
            },
        ],
    }


class EventSelectionTests(unittest.TestCase):
    def test_selects_latest_deadline_that_has_passed(self):
        events = [
            {**EVENT, "id": 5, "deadline_time": "2026-09-20T10:00:00Z"},
            EVENT,
            {**EVENT, "id": 7, "deadline_time": "2026-10-03T10:00:00Z"},
        ]
        now = datetime(2026, 9, 26, 10, 31, tzinfo=timezone.utc)

        self.assertEqual(_target_event(events, now)["id"], 6)
        self.assertEqual(_report_key(EVENT), "2026-27-gw-6")

    def test_selects_first_upcoming_deadline_before_the_season_starts(self):
        events = [
            EVENT,
            {**EVENT, "id": 7, "deadline_time": "2026-10-03T10:00:00Z"},
        ]
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)

        self.assertEqual(_target_event(events, now)["id"], 6)


class ReportFormattingTests(unittest.TestCase):
    def test_formats_captains_chips_transfers_hits_and_wildcard_net_changes(self):
        data = sample_data()
        player_names = {player_id: f"P{player_id}" for player_id in range(1, 47)}

        def fetch_json(url):
            if "/entry/3/event/5/picks/" in url:
                return {
                    "picks": [
                        {"element": player_id}
                        for player_id in [30, *range(32, 46)]
                    ]
                }
            raise AssertionError(url)

        report = "\n\n".join(build_report_blocks(data, player_names, fetch_json))

        self.assertIn("⚽ <b>Gameweek 6 Report</b>", report)
        self.assertIn("Haaland\n• maubeefcherkii", report)
        self.assertIn("Triple Captain\n• Forte Ding", report)
        self.assertIn("Wildcard\n• joshur10", report)
        self.assertIn("maubeefcherkii (No hit)\nDedić → Hall", report)
        self.assertIn("Forte Ding (-4 hit)", report)
        self.assertIn("joshur10 (1 change on WC)", report)
        self.assertIn("IN: P31", report)
        self.assertIn("OUT: P30", report)

    def test_requires_all_fifteen_picks_for_every_team(self):
        data = sample_data()
        data["teamDetails"][1]["players"].pop()

        ready, missing = _data_is_ready(data)

        self.assertFalse(ready)
        self.assertEqual(missing, ["Forte Ding"])

    def test_packs_whole_blocks_without_exceeding_telegram_limit(self):
        messages = _pack_messages(["a" * 3000, "b" * 2000])

        self.assertEqual(len(messages), 2)
        self.assertTrue(all(len(message) <= 4096 for message in messages))

    def test_telegram_http_error_includes_the_api_description(self):
        error = HTTPError(
            "https://api.telegram.org/redacted/sendMessage",
            400,
            "Bad Request",
            {},
            io.BytesIO(
                b'{"ok":false,"error_code":400,"description":"Bad Request: chat not found"}'
            ),
        )
        with patch("telegram_report.urlopen", side_effect=error):
            with self.assertRaisesRegex(RuntimeError, "chat not found"):
                _send_message("secret-token", "-123", "test")

    def test_waits_if_the_formatted_transfers_are_incomplete(self):
        data = sample_data()

        def fetch_json(url):
            if "/entry/1/transfers/" in url:
                return [{"event": 6}]
            if "/entry/2/transfers/" in url:
                return [{"event": 6}, {"event": 6}]
            if "/transfers/" in url:
                return []
            if "/entry/3/event/5/picks/" in url:
                return {
                    "picks": [
                        {"element": player_id}
                        for player_id in [30, *range(32, 46)]
                    ]
                }
            raise AssertionError(url)

        data["teamDetails"][0]["transfers"] = []
        ready, missing = _transfer_data_is_ready(data, 6, fetch_json)

        self.assertFalse(ready)
        self.assertEqual(missing, ["maubeefcherkii"])


class RunnerTests(unittest.TestCase):
    @staticmethod
    def bootstrap(_url):
        return {
            "events": [EVENT],
            "elements": [
                {"id": player_id, "web_name": f"P{player_id}"}
                for player_id in range(1, 47)
            ],
        }

    def test_does_not_fetch_team_data_until_thirty_minutes_after_deadline(self):
        def unexpected_fetch(**_kwargs):
            raise AssertionError("standings should not be fetched")

        result = run(
            now=datetime(2026, 9, 26, 10, 29, tzinfo=timezone.utc),
            fetch_json=self.bootstrap,
            fetch_standings_fn=unexpected_fetch,
        )

        self.assertEqual(result, "too-early")

    def test_sent_tag_stops_fpl_checks_until_the_next_gameweek_window(self):
        def unexpected_fetch(_url):
            raise AssertionError("FPL should not be fetched")

        with patch(
            "telegram_report._git_tags",
            return_value=["telegram-report-2026-27-gw-6-next-9999999999"],
        ):
            result = run(
                now=datetime(2026, 9, 27, tzinfo=timezone.utc),
                fetch_json=unexpected_fetch,
            )

        self.assertEqual(result, "already-sent")

    def test_does_not_send_a_gameweek_from_before_workflow_activation(self):
        activation = datetime(2026, 9, 27, tzinfo=timezone.utc)
        with patch(
            "telegram_report._workflow_activation_time", return_value=activation
        ):
            result = run(
                now=datetime(2026, 9, 28, tzinfo=timezone.utc),
                fetch_json=self.bootstrap,
            )

        self.assertEqual(result, "pre-activation")

    def test_sends_once_then_uses_the_persisted_marker(self):
        sent_messages = []
        standings_calls = []

        def fetch_json(url):
            if url.endswith("bootstrap-static/"):
                return self.bootstrap(url)
            if "/transfers/" in url:
                entry_id = int(url.split("/entry/", 1)[1].split("/", 1)[0])
                if entry_id == 1:
                    return [{"event": 6}]
                if entry_id == 2:
                    return [{"event": 6}, {"event": 6}]
                return []
            if "/entry/3/event/5/picks/" in url:
                return {
                    "picks": [
                        {"element": player_id}
                        for player_id in [30, *range(32, 46)]
                    ]
                }
            raise AssertionError(url)

        def fetch_standings_fn(**_kwargs):
            standings_calls.append(True)
            return sample_data()

        def send_message(_token, _chat_id, text, _thread_id):
            sent_messages.append(text)
            return 123

        with tempfile.TemporaryDirectory() as temporary_directory:
            state_dir = Path(temporary_directory)
            now = datetime(2026, 9, 26, 10, 31, tzinfo=timezone.utc)
            old_environ = dict(os.environ)
            os.environ["TELEGRAM_BOT_TOKEN"] = "test-token"
            os.environ["TELEGRAM_CHAT_ID"] = "-123"
            try:
                first = run(
                    now=now,
                    state_dir=state_dir,
                    fetch_json=fetch_json,
                    fetch_standings_fn=fetch_standings_fn,
                    send_message=send_message,
                )
                second = run(
                    now=now,
                    state_dir=state_dir,
                    fetch_json=fetch_json,
                    fetch_standings_fn=fetch_standings_fn,
                    send_message=send_message,
                )
            finally:
                os.environ.clear()
                os.environ.update(old_environ)

        self.assertEqual(first, "sent")
        self.assertEqual(second, "already-sent")
        self.assertEqual(len(sent_messages), 1)
        self.assertEqual(len(standings_calls), 1)


if __name__ == "__main__":
    unittest.main()
