"""Send the post-deadline FPL league report to Telegram.

The script is intended to be invoked by a short-lived scheduler.  It exits
quickly before the reporting window and after a gameweek has been sent; FPL
team data is only fetched from 30 minutes after the deadline until it becomes
available.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from config import FPL_API_URL
from services.fpl import _get_json, fetch_standings

JsonObject = dict[str, Any]
JsonFetcher = Callable[[str], JsonObject]
REPORT_DELAY = timedelta(minutes=30)
STATE_DIR = Path(__file__).parent / "data" / "telegram"
TELEGRAM_MESSAGE_LIMIT = 4096
CHIP_NAMES = {
    "WC": "Wildcard",
    "FH": "Free Hit",
    "TC": "Triple Captain",
    "BB": "Bench Boost",
}


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _target_event(events: Iterable[JsonObject], now: datetime) -> JsonObject:
    dated_events = [
        (event, _parse_time(event["deadline_time"]))
        for event in events
        if event.get("deadline_time")
    ]
    if not dated_events:
        raise RuntimeError("FPL returned no gameweek deadlines")

    passed = [item for item in dated_events if item[1] <= now]
    if passed:
        return max(passed, key=lambda item: item[1])[0]
    return min(dated_events, key=lambda item: item[1])[0]


def _event_deadline(event: JsonObject) -> datetime:
    return _parse_time(event["deadline_time"])


def _season_key(deadline: datetime) -> str:
    start_year = deadline.year if deadline.month >= 7 else deadline.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"


def _report_key(event: JsonObject) -> str:
    return f"{_season_key(_event_deadline(event))}-gw-{event['id']}"


def _state_path(event: JsonObject, state_dir: Path = STATE_DIR) -> Path:
    return state_dir / f"{_report_key(event)}.json"


def _git_tags(pattern: str) -> list[str]:
    try:
        result = subprocess.run(
            ["git", "tag", "--list", pattern],
            cwd=Path(__file__).parent,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return result.stdout.splitlines()


def _workflow_activation_time() -> datetime | None:
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                "-1",
                "--diff-filter=A",
                "--format=%cI",
                "--",
                ".github/workflows/telegram-report.yml",
            ],
            cwd=Path(__file__).parent,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    value = result.stdout.strip()
    return _parse_time(value) if value else None


def _deferred_by_sent_tag(now: datetime, state_dir: Path) -> bool:
    if state_dir.resolve() != STATE_DIR.resolve():
        return False
    next_checks = []
    for tag in _git_tags("telegram-report-*-next-*"):
        try:
            next_checks.append(int(tag.rsplit("-next-", 1)[1]))
        except (IndexError, ValueError):
            continue
    if not next_checks:
        return False
    next_check = datetime.fromtimestamp(max(next_checks), timezone.utc)
    if now < next_check:
        print(f"Previous report sent; no FPL check needed until {next_check.isoformat()}")
        return True
    return False


def _event_was_sent(event: JsonObject, state_dir: Path) -> bool:
    if _state_path(event, state_dir).exists():
        return True
    if state_dir.resolve() != STATE_DIR.resolve():
        return False
    return bool(_git_tags(f"telegram-report-{_report_key(event)}-next-*"))


def _data_is_ready(data: JsonObject) -> tuple[bool, list[str]]:
    details = {team["id"]: team for team in data.get("teamDetails", [])}
    missing = []
    for team in data.get("standings", []):
        detail = details.get(team["id"])
        if detail is None or len(detail.get("players", [])) != 15:
            missing.append(team.get("team") or str(team["id"]))
    return bool(data.get("standings")) and not missing, missing


def _transfer_data_is_ready(
    data: JsonObject, gameweek_id: int, fetch_json: JsonFetcher
) -> tuple[bool, list[str]]:
    missing = []
    for team in data.get("teamDetails", []):
        try:
            raw_transfers = fetch_json(
                f"{FPL_API_URL}/entry/{team['id']}/transfers/"
            )
        except Exception:
            missing.append(team["team"])
            continue
        if not isinstance(raw_transfers, list):
            missing.append(team["team"])
            continue

        event_transfer_count = sum(
            transfer.get("event") == gameweek_id for transfer in raw_transfers
        )
        if (
            team.get("chip") not in {"WC", "FH"}
            and event_transfer_count != len(team.get("transfers", []))
        ):
            missing.append(team["team"])
            continue
        if team.get("chip") in {"WC", "FH"} and gameweek_id > 1:
            if _previous_squad(team["id"], gameweek_id, fetch_json) is None:
                missing.append(team["team"])
    return not missing, missing


def _captain_blocks(team_details: Iterable[JsonObject]) -> list[str]:
    captains: dict[str, list[str]] = defaultdict(list)
    for team in team_details:
        captain = next(
            (player for player in team.get("players", []) if player.get("isCaptain")),
            None,
        )
        if captain is not None:
            captains[captain["name"]].append(team["team"])

    if not captains:
        return ["Captain data unavailable"]
    return [
        "\n".join(
            [html.escape(captain), *(f"• {html.escape(team)}" for team in teams)]
        )
        for captain, teams in sorted(
            captains.items(), key=lambda item: (-len(item[1]), item[0].lower())
        )
    ]


def _chip_blocks(team_details: Iterable[JsonObject]) -> list[str]:
    chips: dict[str, list[str]] = defaultdict(list)
    for team in team_details:
        if team.get("chip"):
            chips[CHIP_NAMES.get(team["chip"], team["chip"])].append(team["team"])

    if not chips:
        return ["No chips played"]
    return [
        "\n".join([html.escape(chip), *(f"• {html.escape(team)}" for team in teams)])
        for chip, teams in sorted(chips.items())
    ]


def _previous_squad(
    entry_id: int, gameweek_id: int, fetch_json: JsonFetcher
) -> set[int] | None:
    if gameweek_id <= 1:
        return None
    try:
        data = fetch_json(
            f"{FPL_API_URL}/entry/{entry_id}/event/{gameweek_id - 1}/picks/"
        )
    except Exception:
        return None
    picks = data.get("picks") if isinstance(data, dict) else None
    if not isinstance(picks, list) or len(picks) != 15:
        return None
    return {pick["element"] for pick in picks}


def _unlimited_transfer_block(
    team: JsonObject,
    gameweek_id: int,
    player_names: dict[int, str],
    fetch_json: JsonFetcher,
) -> str:
    chip = team["chip"]
    current_squad = {player["id"] for player in team.get("players", [])}
    previous_squad = _previous_squad(team["id"], gameweek_id, fetch_json)
    if previous_squad is None:
        changes = team.get("transfers", [])
        return "\n".join(
            [
                f"{html.escape(team['team'])} ({len(changes)} changes on {chip})",
                "Transfer details unavailable",
            ]
        )

    players_in = sorted(
        current_squad - previous_squad,
        key=lambda player: player_names.get(player, ""),
    )
    players_out = sorted(
        previous_squad - current_squad,
        key=lambda player: player_names.get(player, ""),
    )
    change_count = len(players_in)
    change_label = "change" if change_count == 1 else "changes"
    in_names = ", ".join(
        html.escape(player_names.get(player, f"Player {player}"))
        for player in players_in
    )
    out_names = ", ".join(
        html.escape(player_names.get(player, f"Player {player}"))
        for player in players_out
    )
    return "\n".join(
        [
            f"{html.escape(team['team'])} ({change_count} {change_label} on {chip})",
            f"IN: {in_names or 'None'}",
            f"OUT: {out_names or 'None'}",
        ]
    )


def _transfer_block(
    team: JsonObject,
    gameweek_id: int,
    player_names: dict[int, str],
    fetch_json: JsonFetcher,
) -> str:
    if team.get("chip") in {"WC", "FH"}:
        return _unlimited_transfer_block(
            team, gameweek_id, player_names, fetch_json
        )

    cost = team.get("transferCost") or 0
    hit = f"-{cost} hit" if cost else "No hit"
    lines = [f"{html.escape(team['team'])} ({hit})"]
    transfers = team.get("transfers", [])
    lines.extend(
        f"{html.escape(transfer['out'])} → {html.escape(transfer['in'])}"
        for transfer in transfers
    )
    if not transfers:
        lines.append("No transfers")
    return "\n".join(lines)


def build_report_blocks(
    data: JsonObject,
    player_names: dict[int, str],
    fetch_json: JsonFetcher = _get_json,
) -> list[str]:
    gameweek_id = data["gameweek"]["id"]
    title = f"⚽ <b>Gameweek {gameweek_id} Report</b>"
    details = data["teamDetails"]
    blocks = [title, "— 👑 <b>CAPTAINS</b> —"]
    blocks.extend(_captain_blocks(details))
    blocks.append("— 🃏 <b>CHIPS</b> —")
    blocks.extend(_chip_blocks(details))
    blocks.append("— 🔄 <b>TRANSFERS</b> —")
    blocks.extend(
        _transfer_block(team, gameweek_id, player_names, fetch_json)
        for team in details
    )
    return blocks


def _pack_messages(blocks: Iterable[str]) -> list[str]:
    messages: list[str] = []
    current = ""
    for block in blocks:
        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= TELEGRAM_MESSAGE_LIMIT:
            current = candidate
            continue
        if current:
            messages.append(current)
        if len(block) > TELEGRAM_MESSAGE_LIMIT:
            raise RuntimeError("A report section exceeds Telegram's message limit")
        current = block
    if current:
        messages.append(current)
    return messages


def _send_message(
    token: str, chat_id: str, text: str, thread_id: int | None = None
) -> int:
    payload: JsonObject = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    request = Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=20) as response:
            result = json.load(response)
    except HTTPError as error:
        try:
            error_payload = json.loads(error.read().decode("utf-8"))
            description = error_payload.get("description")
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError):
            description = None
        detail = description or error.reason or f"HTTP {error.code}"
        raise RuntimeError(f"Telegram API rejected the message: {detail}") from None
    if not result.get("ok"):
        raise RuntimeError(result.get("description") or "Telegram rejected the report")
    return int(result["result"]["message_id"])


def run(
    *,
    now: datetime | None = None,
    dry_run: bool = False,
    allow_past: bool = False,
    state_dir: Path = STATE_DIR,
    fetch_json: JsonFetcher = _get_json,
    fetch_standings_fn: Callable[..., JsonObject] = fetch_standings,
    send_message: Callable[[str, str, str, int | None], int] = _send_message,
) -> str:
    now = now or datetime.now(timezone.utc)
    if _deferred_by_sent_tag(now, state_dir):
        return "already-sent"

    bootstrap = fetch_json(f"{FPL_API_URL}/bootstrap-static/")
    event = _target_event(bootstrap["events"], now)
    activation_time = _workflow_activation_time()
    if (
        not allow_past
        and activation_time is not None
        and _event_deadline(event) < activation_time
    ):
        print(
            f"Skipping {_report_key(event)} because its deadline predates "
            "Telegram workflow activation"
        )
        return "pre-activation"
    ready_at = _event_deadline(event) + REPORT_DELAY
    if now < ready_at:
        print(f"Waiting until {ready_at.isoformat()} for {_report_key(event)}")
        return "too-early"

    marker = _state_path(event, state_dir)
    if _event_was_sent(event, state_dir):
        print(f"Report already sent: {_report_key(event)}")
        return "already-sent"

    try:
        data = fetch_standings_fn(
            fetch_json=fetch_json,
            gameweek_id=event["id"],
            read_snapshot=False,
        )
    except Exception as error:
        print(f"FPL data is not ready yet: {error}")
        return "not-ready"

    ready, missing = _data_is_ready(data)
    if not ready:
        print(f"FPL picks are not ready for: {', '.join(missing) or 'league'}")
        return "not-ready"

    transfers_ready, missing_transfers = _transfer_data_is_ready(
        data, event["id"], fetch_json
    )
    if not transfers_ready:
        print(
            "FPL transfers are not ready for: "
            f"{', '.join(missing_transfers) or 'league'}"
        )
        return "not-ready"

    player_names = {
        player["id"]: player.get("web_name")
        or f"{player.get('first_name', '')} {player.get('second_name', '')}".strip()
        for player in bootstrap.get("elements", [])
    }
    messages = _pack_messages(build_report_blocks(data, player_names, fetch_json))
    if dry_run:
        print("\n\n--- TELEGRAM MESSAGE ---\n\n".join(messages))
        return "dry-run"

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        raise RuntimeError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required")
    thread_value = os.environ.get("TELEGRAM_THREAD_ID")
    thread_id = int(thread_value) if thread_value else None
    message_ids = [
        send_message(token, chat_id, message, thread_id) for message in messages
    ]

    future_deadlines = [
        _event_deadline(future_event) + REPORT_DELAY
        for future_event in bootstrap["events"]
        if _event_deadline(future_event) > _event_deadline(event)
    ]
    next_check = min(future_deadlines, default=now + timedelta(days=7))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "gameweek": event["id"],
                "reportKey": _report_key(event),
                "sentAt": now.isoformat(),
                "messageIds": message_ids,
                "nextCheckAt": next_check.isoformat(),
                "nextCheckEpoch": int(next_check.timestamp()),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Sent {_report_key(event)} in {len(message_ids)} message(s)")
    return "sent"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--dry-run", action="store_true", help="print the report without sending it"
    )
    parser.add_argument(
        "--allow-past",
        action="store_true",
        help="allow a manual preview or send for a pre-activation deadline",
    )
    args = parser.parse_args()
    try:
        run(dry_run=args.dry_run, allow_past=args.allow_past)
    except Exception as error:
        print(f"Telegram report failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
