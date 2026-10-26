import unittest

from services.fpl import (
    _apply_live_gameweek_points,
    _build_player_context,
    _format_pairs,
    _resolve_auto_substitutions,
    _resolve_entry_picks,
)


class PlayerStatusTests(unittest.TestCase):
    def setUp(self):
        self.elements = [{"id": 10, "web_name": "Player", "team": 1}]
        self.teams = [
            {"id": 1, "short_name": "ONE"},
            {"id": 2, "short_name": "TWO"},
            {"id": 3, "short_name": "THR"},
        ]

    def player_context(self, fixtures, minutes):
        _, get_player_context, _ = _build_player_context(
            self.elements,
            self.teams,
            fixtures,
            [{"id": 10, "stats": {"total_points": 0, "minutes": minutes}}],
        )
        return get_player_context(10)

    def test_marks_zero_minute_player_as_did_not_play_after_fixture_finishes(self):
        context = self.player_context(
            [
                {
                    "id": 100,
                    "team_h": 1,
                    "team_a": 2,
                    "started": True,
                    "finished": True,
                }
            ],
            minutes=0,
        )

        self.assertEqual(context["fixtureTime"], "Done")
        self.assertEqual(context["matchStatus"], "Did Not Play")

    def test_keeps_done_status_for_player_who_played(self):
        context = self.player_context(
            [
                {
                    "id": 100,
                    "team_h": 1,
                    "team_a": 2,
                    "started": True,
                    "finished": True,
                }
            ],
            minutes=1,
        )

        self.assertEqual(context["fixtureTime"], "Done")
        self.assertIsNone(context["matchStatus"])

    def test_waits_for_every_double_gameweek_fixture_to_finish(self):
        fixtures = [
            {
                "id": 100,
                "team_h": 1,
                "team_a": 2,
                "started": True,
                "finished": True,
                "kickoff_time": "2024-08-18T07:00:00Z",
            },
            {
                "id": 101,
                "team_h": 3,
                "team_a": 1,
                "started": False,
                "finished": False,
                "kickoff_time": "2024-08-21T19:00:00Z",
            },
        ]

        context = self.player_context(fixtures, minutes=0)
        self.assertEqual(context["fixtureTime"], "Thu 03:00")
        self.assertIsNone(context["matchStatus"])

        fixtures[1]["started"] = True
        fixtures[1]["finished"] = True
        context = self.player_context(fixtures, minutes=0)
        self.assertEqual(context["fixtureTime"], "Done")
        self.assertEqual(context["matchStatus"], "Did Not Play")


class AutoSubstitutionTests(unittest.TestCase):
    def setUp(self):
        self.positions = {
            1: 1,
            2: 4,
            3: 3,
            4: 2,
            5: 2,
            6: 2,
            7: 3,
            8: 3,
            9: 3,
            10: 4,
            11: 4,
            12: 1,
            13: 3,
            14: 2,
            15: 4,
        }
        self.picks = [
            {
                "element": player_id,
                "position": player_id,
                "multiplier": 2 if player_id == 2 else int(player_id <= 11),
                "is_captain": player_id == 2,
                "is_vice_captain": player_id == 3,
            }
            for player_id in range(1, 16)
        ]
        self.eligible = set(self.positions) - {2}

    def resolve(self, *, did_not_play=None, active_chip=None, automatic_subs=None):
        return _resolve_entry_picks(
            {
                "picks": self.picks,
                "active_chip": active_chip,
                "automatic_subs": automatic_subs or [],
            },
            did_not_play or {2},
            self.eligible - (did_not_play or {2}),
            self.positions,
        )

    @staticmethod
    def by_id(picks):
        return {pick["element"]: pick for pick in picks}

    def test_projects_auto_sub_and_captain_handover_in_the_same_refresh(self):
        elements = [
            {
                "id": player_id,
                "team": 1 if player_id == 2 else 2,
                "element_type": position,
            }
            for player_id, position in self.positions.items()
        ]
        resolved_data = _resolve_auto_substitutions(
            {1: {"picks": self.picks}},
            elements,
            [
                {"team_h": 1, "team_a": 3, "started": True, "finished": True},
                {"team_h": 2, "team_a": 4, "started": False, "finished": False},
            ],
            [{"id": 2, "stats": {"minutes": 0, "total_points": 0}}],
        )
        picks = self.by_id(resolved_data[1]["picks"])

        self.assertEqual(picks[2]["autoSubRole"], "out")
        self.assertEqual(picks[2]["autoSubPartnerId"], 13)
        self.assertEqual(picks[2]["multiplier"], 0)
        self.assertEqual(picks[13]["autoSubRole"], "in")
        self.assertEqual(picks[13]["autoSubPartnerId"], 2)
        self.assertEqual(picks[13]["multiplier"], 1)
        self.assertEqual(picks[3]["multiplier"], 2)

        standings = [
            {"id": 1, "team": "Alpha", "gameweekPoints": 0, "totalPoints": 100}
        ]
        _apply_live_gameweek_points(
            standings,
            resolved_data,
            [
                {"id": 3, "stats": {"total_points": 5}},
                {"id": 13, "stats": {"total_points": 4}},
            ],
        )
        self.assertEqual(standings[0]["gameweekPoints"], 14)

        beta = {"id": 2, "team": "Beta", "gameweekPoints": 6, "totalPoints": 200}
        pair = _format_pairs(
            [standings[0], beta], (("Alpha & Beta", (1, 2)),)
        )[0]
        self.assertEqual(pair["gameweekPoints"], 20)

    def test_triple_captain_chip_moves_to_the_vice_captain(self):
        picks = self.by_id(self.resolve(active_chip="3xc"))

        self.assertEqual(picks[2]["multiplier"], 0)
        self.assertEqual(picks[3]["multiplier"], 3)

    def test_no_captain_multiplier_when_captain_and_vice_both_do_not_play(self):
        picks = self.by_id(self.resolve(did_not_play={2, 3}))

        self.assertEqual(picks[2]["multiplier"], 0)
        self.assertEqual(picks[3]["multiplier"], 0)
        self.assertLessEqual(max(pick["multiplier"] for pick in picks.values()), 1)

    def test_bench_boost_prevents_auto_sub_but_still_hands_over_captaincy(self):
        picks = self.by_id(self.resolve(active_chip="bboost"))

        self.assertNotIn("autoSubRole", picks[2])
        self.assertNotIn("autoSubRole", picks[13])
        self.assertEqual(picks[2]["multiplier"], 0)
        self.assertEqual(picks[3]["multiplier"], 2)
        self.assertEqual(picks[13]["multiplier"], 1)

    def test_skips_first_bench_player_when_the_formation_would_be_invalid(self):
        picks = self.by_id(self.resolve(did_not_play={4}))

        self.assertNotIn("autoSubRole", picks[13])
        self.assertEqual(picks[14]["autoSubRole"], "in")
        self.assertEqual(picks[4]["autoSubPartnerId"], 14)

    def test_only_a_goalkeeper_can_replace_a_goalkeeper(self):
        picks = self.by_id(self.resolve(did_not_play={1}))

        self.assertEqual(picks[1]["autoSubRole"], "out")
        self.assertEqual(picks[12]["autoSubRole"], "in")

    def test_uses_fpl_official_auto_substitution_when_available(self):
        official_picks = [dict(pick) for pick in self.picks]
        for pick in official_picks:
            if pick["element"] == 2:
                pick["multiplier"] = 0
            elif pick["element"] == 3:
                pick["multiplier"] = 2
            elif pick["element"] == 15:
                pick["multiplier"] = 1
        self.picks = official_picks

        picks = self.by_id(
            self.resolve(automatic_subs=[{"element_out": 2, "element_in": 15}])
        )

        self.assertNotIn("autoSubRole", picks[13])
        self.assertEqual(picks[15]["autoSubRole"], "in")
        self.assertEqual(picks[2]["autoSubPartnerId"], 15)


if __name__ == "__main__":
    unittest.main()
