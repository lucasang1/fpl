# FPL League Standings

Live Fantasy Premier League standings for league `713788`.

The app serves a static frontend from `public/` and a small Python API at
`/api/standings`. It fetches Fantasy Premier League data on demand, caches live
responses briefly, and stores completed gameweek snapshots so locked weeks can
be replayed without refetching every team.

## Features

- Duo and individual standings views
- Gameweek selector for the current and completed gameweeks
- In-play and to-start player counts for each team
- Team detail cards with picks, chips, transfers, captaincy, bench, and point
  breakdowns
- Duo importance view showing which players matter most to each pairing
- Light/dark theme toggle with the user's choice saved locally
- Frozen snapshots for completed gameweeks

## Run Locally

```sh
python3 run.py
```

Then open `http://localhost:8000`.

Run the test suite with:

```sh
python3 -m unittest discover -v
```

## Configuration

Configuration defaults live in `config.py`. Override them with environment
variables when needed.

| Variable | Default | Description |
| --- | --- | --- |
| `FPL_LEAGUE_ID` | `713788` | Classic league ID to display. |
| `PORT` | `8000` | Local HTTP server port. |
| `FPL_TEAM_CARD_IMAGE` | `badge` | Use `badge` for FPL club badges or `headshot` for local manager images. |
| `FPL_GAMEWEEK_SNAPSHOT_DIR` | `data/gameweeks` | Directory used to read/write completed gameweek snapshots. |

Pairings and local headshot paths are configured in `config.py`.

## API

The frontend reads standings from:

```text
GET /api/standings
```

Optional query parameters:

- `event=<gameweek>` returns a specific available gameweek.
- `refresh=1` bypasses the in-process cache and ignores saved snapshots for
  that request.

The response includes league metadata, the selected gameweek, available
gameweeks, refresh policy, pair standings, individual standings, duo importance,
and team details.

## Snapshots And Refreshing

When all fixtures in a gameweek are finished, the API writes a snapshot to
`data/gameweeks/gw-<id>.json` by default. Future requests for locked gameweeks
reuse that file unless `refresh=1` is supplied.

Live gameweeks advertise a `refreshPolicy`:

- `live`: poll every 20 seconds while a match is in play.
- `settling`: poll every 2 minutes shortly after a match finishes.
- `frozen`: stop polling when there are no recent live matches.

The local server also keeps an in-memory cache per selected gameweek, using the
same refresh policy to choose its cache duration.

## Deploy To Vercel

Import the repository into Vercel and leave the Framework Preset as **Other**.
Vercel serves the files in `public/` and deploys `api/standings.py` at
`/api/standings`; no build command is required.

Set `FPL_LEAGUE_ID` in the Vercel project environment variables only when
overriding the league ID from `config.py`. If you want persistent snapshots on a
traditional Python host, point `FPL_GAMEWEEK_SNAPSHOT_DIR` at a writable
directory. Static-only hosts such as GitHub Pages cannot serve the API endpoint.
