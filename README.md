# FPL league standings

Live standings for FPL league `713788`. Data is fetched when the page loads and when Refresh is pressed.

## Run locally

```sh
python3 run.py
```

Configuration lives in `config.py`. Set `FPL_LEAGUE_ID` or `PORT` as environment variables to override the defaults.

Run the tests with:

```sh
python3 -m unittest discover -v
```

Deploy `python3 run.py` to a Python host. Static-only hosts such as GitHub Pages cannot serve the API endpoint.
