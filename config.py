import os
from pathlib import Path

LEAGUE_ID = int(os.getenv("FPL_LEAGUE_ID", "713788"))
FPL_API_URL = "https://fantasy.premierleague.com/api"
PUBLIC_DIR = Path(__file__).parent / "public"
PORT = int(os.getenv("PORT", "8000"))

PAIRINGS = (
    ("Luc & Josh", (2020069, 3497860)),
    ("Praeman & Ding", (646370, 712762)),
    ("Wob & Syuaib", (3430323, 3425313)),
    ("Isaac & Chia Yin", (2168885, 369209)),
    ("Mau & Mau", (2062502, 2062502)),
)

HEADSHOTS = {
    2020069: "/headshots/lucas.png",
    3497860: "/headshots/joshur.png",
    646370: "/headshots/praeman.png",
    712762: "/headshots/ding.png",
    3430323: "/headshots/vaibhav.png",
    3425313: "/headshots/syuaib.png",
    2168885: "/headshots/isaac.png",
    369209: "/headshots/chia%20yin.png",
    2062502: "/headshots/maurice.png",
}
