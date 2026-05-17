import os
from PyQt6.QtGui import QFontDatabase

# File paths
ASSET_DIR = os.path.join("data", "assets")
MECH_ASSET_DIR = os.path.join(ASSET_DIR, "exosuit")
DATA_DIR = os.path.join("data")

# Shit used by the exosuit editor
MOUNTS_JSON = os.path.join(DATA_DIR, "mounts.json")
WEAPONS_JSON = os.path.join(DATA_DIR, "exosuit_weapons.json")

# Background & CGW Logo
BG_PATH = os.path.join(ASSET_DIR, "bg.png")
LOGO_PATH = os.path.join(ASSET_DIR, "cgw.png")

# Audio files
SFX_DIR = os.path.join(ASSET_DIR, "sfx")
SFX_HOVER = os.path.abspath(os.path.join(SFX_DIR, "Exosuit_inspect.wav"))
SFX_CYCLE = os.path.abspath(os.path.join(SFX_DIR, "Exo_cycle.wav"))
SFX_SAVE = os.path.abspath(os.path.join(SFX_DIR, "Exo_Save.wav"))

# Colors!!!
COLOR_PRIMARY = "#5ce372"
COLOR_BG_DARK = "#0a0a0a"
COLOR_BG_DARKER = "#050505"
COLOR_TEXT_LIGHT = "#FFFFFF"
COLOR_TEXT_WARN = "#FFEF00"

def load_sinclair_font():
    # Tries loading FS Sinclair, with Consolas as a fallback. 
    font_family = "Consolas"
    font_path = os.path.join(ASSET_DIR, "fonts", "FS Sinclair Pack", "FS Sinclair Medium.otf")
    
    if os.path.exists(font_path):
        font_id = QFontDatabase.addApplicationFont(font_path)
        if font_id != -1:
            font_family = QFontDatabase.applicationFontFamilies(font_id)[0]
            
    return font_family