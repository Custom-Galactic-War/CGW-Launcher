import os
import sys
from PyQt6.QtGui import QFontDatabase

# Everything the launcher reads or writes lives next to the launcher itself.
# Users place the launcher and its 'files' folder directly inside their
# 'Helldivers 2' folder, so BASE_DIR is that folder and the game's 'bin'
# subfolder sits right beside us.
def _compute_base_dir():
    if getattr(sys, "frozen", False):
        # PyInstaller build: the directory containing the launcher executable.
        return os.path.dirname(os.path.abspath(sys.executable))
    # Running from source: the directory containing this file.
    return os.path.dirname(os.path.abspath(__file__))


BASE_DIR = _compute_base_dir()
FILES_DIR = os.path.join(BASE_DIR, "files")  # ships alongside the launcher
BIN_DIR = os.path.join(BASE_DIR, "bin")      # the Helldivers 2 'bin' folder

# File paths
ASSET_DIR = os.path.join(FILES_DIR, "assets")
MECH_ASSET_DIR = os.path.join(ASSET_DIR, "exosuit")

# Used by the exosuit editor. MOUNTS_JSON is the copy in the 'files' folder;
# the editor targets the copy inside 'bin' instead when one exists there
# (see functions.get_active_mounts_json_path).
MOUNTS_JSON = os.path.join(FILES_DIR, "mounts.json")
WEAPONS_JSON = os.path.join(FILES_DIR, "exosuit_weapons.json")

# Background & CGW Logo
BG_PATH = os.path.join(ASSET_DIR, "bg.png")
LOGO_PATH = os.path.join(ASSET_DIR, "cgw.png")

# Audio files
SFX_DIR = os.path.join(ASSET_DIR, "sfx")
SFX_HOVER = os.path.join(SFX_DIR, "Exosuit_inspect.wav")
SFX_CYCLE = os.path.join(SFX_DIR, "Exo_cycle.wav")
SFX_SAVE = os.path.join(SFX_DIR, "Exo_Save.wav")

# Colors!!!
COLOR_PRIMARY = "#5ce372"
COLOR_BG_DARK = "#0a0a0a"
COLOR_BG_DARKER = "#050505"
COLOR_TEXT_LIGHT = "#FFFFFF"
COLOR_TEXT_WARN = "#FFEF00"

# URL of a static "Join Lobby" redirect page that bounces visitors from an
# https:// page into steam://joinlobby/553850/... — needed because Discord
# rejects steam:// URLs in Rich Presence buttons. The page itself lives in
# this repo at docs/index.html.
#
# Deploy steps (one-time):
#   1. Push docs/index.html to a public GitHub repo (or any static host).
#   2. Enable GitHub Pages on that repo (Settings -> Pages -> Branch: main,
#      Folder: /docs). GitHub Pages only exposes "/ (root)" and "/docs" as
#      folder choices, which is why the page lives in docs/.
#   3. Replace the URL below with your own Pages URL (it must end with a /).
#
# If left blank, the launcher will still let you set a lobby and update
# Discord party info (Hosting Lobby 1/4) — it just won't add a clickable
# "Join Lobby" button on the Discord presence card.
LOBBY_REDIRECT_BASE = "https://Custom-Galactic-War.github.io/CGW-Launcher/"

def load_sinclair_font():
    if sys.platform.startswith("win"):
        font_family = "Consolas"
    elif sys.platform == "darwin":
        font_family = "Menlo"
    else:
        font_family = "DejaVu Sans Mono"

    font_path = os.path.join(ASSET_DIR, "fonts", "FS Sinclair Pack", "FS Sinclair Medium.otf")

    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]

    return font_family