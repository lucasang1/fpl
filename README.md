# FPL league standings

Live standings for FPL league `713788`. Data is fetched when the page loads and when Refresh is pressed.

## Run locally

```sh
python3 run.py
```

Configuration lives in `config.py`. Set `FPL_LEAGUE_ID` or `PORT` as environment variables to override the defaults. Set `FPL_TEAM_CARD_IMAGE=headshot` to use manager headshots in the team card; the default is `badge`.

Run the tests with:

```sh
python3 -m unittest discover -v
```

## Deploy to Vercel

Import the repository into Vercel and leave the Framework Preset as **Other**. Vercel serves
the files in `public/` and deploys `api/standings.py` at `/api/standings`; no build command is
required. Set `FPL_LEAGUE_ID` in the Vercel project environment variables only when overriding
the league ID from `config.py`.

For a traditional Python host, run `python3 run.py`. Static-only hosts such as GitHub Pages
cannot serve the API endpoint.
