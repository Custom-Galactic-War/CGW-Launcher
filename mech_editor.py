import os
import json
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QVBoxLayout, QWidget
)
from PyQt6.QtGui import QPixmap, QCursor, QPainter
from PyQt6.QtCore import Qt, QUrl
from PyQt6.QtMultimedia import QSoundEffect

import constants
import functions
from button_cta import InteractiveCTA


# Added some comments to make this a bit less of a fucking mess

# Order in which clicking the chassis sprite cycles forward.
CHASSIS_ORDER = [
    "EXO-45 Patriot Exosuit",
    "EXO-49 Emancipator Exosuit",
    "EXO-51 Lumberer Exosuit",
    "EXO-55 Breakthrough Exosuit",
]

# Weapons that any chassis can mount on either arm.
GENERIC_WEAPONS = [
    "EXO-45 Patriot Exosuit Missile Launcher",
    "EXO-45 Patriot Exosuit Gatling Gun",
    "Hulk Fusion Autocannon",
    "Hulk Incendiary Mortar",
    "Hulk Rockets MK2",
]

# Side-locked Emancipator autocannon variants — available on every chassis, but
# only on the arm whose orientation matches the asset.
EMANCIPATOR_LEFT  = "EXO-49 Emancipator Exosuit Autocannon Left"
EMANCIPATOR_RIGHT = "EXO-49 Emancipator Exosuit Autocannon Right"

# Chassis-locked arms — only selectable when editing the matching chassis.
LUMBERER_WEAPONS = [
    "EXO-51 Lumberer Flamethrower",
    "EXO-51 Lumberer Anti-Tank Cannon",
]
BREAKTHROUGH_WEAPONS = [
    "EXO-55 Breakthrough Shield",
    "EXO-55 Breakthrough Flak Cannon",
]

# Defaults are written only for chassis missing from mounts.json on first load.
CANONICAL_DEFAULTS = {
    "EXO-45 Patriot Exosuit":      ["EXO-45 Patriot Exosuit Missile Launcher",
                                    "EXO-45 Patriot Exosuit Gatling Gun"],
    "EXO-49 Emancipator Exosuit":  [EMANCIPATOR_LEFT, EMANCIPATOR_RIGHT],
    "EXO-51 Lumberer Exosuit":     ["EXO-51 Lumberer Flamethrower",
                                    "EXO-51 Lumberer Anti-Tank Cannon"],
    "EXO-55 Breakthrough Exosuit": ["EXO-55 Breakthrough Shield",
                                    "EXO-55 Breakthrough Flak Cannon"],
}


def allowed_weapons_for(chassis, side):
    """Return the click-cycle list of weapons selectable on the given arm of
    the given chassis. Order matters — it IS the cycle order."""
    weapons = list(GENERIC_WEAPONS)
    # The Emancipator autocannon has dedicated L/R sprites; pick the matching one.
    weapons.append(EMANCIPATOR_LEFT if side == "left" else EMANCIPATOR_RIGHT)
    # Lumberer + Breakthrough share both arm pools — they're bundled in the
    # same warbond, so owning either unlocks the other's arms.
    if chassis in ("EXO-51 Lumberer Exosuit", "EXO-55 Breakthrough Exosuit"):
        weapons.extend(LUMBERER_WEAPONS)
        weapons.extend(BREAKTHROUGH_WEAPONS)
    return weapons


# JSON helpers

def read_json_safely(filepath, default_return):
    if not os.path.exists(filepath):
        return default_return
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return default_return


def load_weapon_manifest():
    data = read_json_safely(constants.WEAPONS_JSON, {})
    return data.get("exosuit_weapons", [])


def _canonical_chassis_key(raw_key):
    """Match a possibly-miscased mounts.json key to its canonical chassis name.
    Returns None if it's not one of our 4 chassis."""
    raw_lower = raw_key.lower()
    for canonical in CHASSIS_ORDER:
        if canonical.lower() == raw_lower:
            return canonical
    return None


def load_all_loadouts():
    """Return a dict[chassis -> {"left": str, "right": str}] for all 4 chassis.
    Existing entries in mounts.json are preserved (with case normalization);
    missing chassis are filled from CANONICAL_DEFAULTS."""
    raw = read_json_safely(constants.MOUNTS_JSON, {})

    loadouts = {}
    for raw_key, paths in raw.items():
        canonical = _canonical_chassis_key(raw_key)
        if not canonical:
            continue  # Unknown key — leave it alone; it's preserved on save.
        if isinstance(paths, list) and len(paths) >= 2:
            loadouts[canonical] = {
                "left":  paths[0].get("path", "") if isinstance(paths[0], dict) else "",
                "right": paths[1].get("path", "") if isinstance(paths[1], dict) else "",
            }

    for chassis in CHASSIS_ORDER:
        if chassis not in loadouts:
            left, right = CANONICAL_DEFAULTS[chassis]
            loadouts[chassis] = {"left": left, "right": right}

    return loadouts


def save_all_loadouts(loadouts):
    """Write the full 4-chassis loadout back to mounts.json. Top-level keys in
    the existing file that AREN'T one of our 4 chassis are preserved untouched
    (defensive — in case the mod adds future entries). Case-variant keys of
    canonical chassis are dropped so we don't leave orphans behind."""
    existing = read_json_safely(constants.MOUNTS_JSON, {})

    out = {}
    for raw_key, val in existing.items():
        if _canonical_chassis_key(raw_key) is None:
            out[raw_key] = val

    for chassis in CHASSIS_ORDER:
        pair = loadouts.get(chassis) or {
            "left":  CANONICAL_DEFAULTS[chassis][0],
            "right": CANONICAL_DEFAULTS[chassis][1],
        }
        out[chassis] = [
            {"path": pair["left"]},
            {"path": pair["right"]},
        ]

    with open(constants.MOUNTS_JSON, 'w') as f:
        json.dump(out, f, indent=4)


# Graphics items

class HardpointItem(QGraphicsPixmapItem):
    def __init__(self, node_id, default_weapon_name, weapon_list, x_offset, y_offset):
        super().__init__()
        self.node_id = node_id
        self.weapon_list = weapon_list

        self.cycle_sound = QSoundEffect()
        if os.path.exists(constants.SFX_CYCLE):
            self.cycle_sound.setSource(QUrl.fromLocalFile(constants.SFX_CYCLE))
            self.cycle_sound.setVolume(0.4)

        self.current_index = self.weapon_list.index(default_weapon_name) if default_weapon_name in self.weapon_list else 0
        self.current_weapon = self.weapon_list[self.current_index] if self.weapon_list else ""

        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setPos(x_offset, y_offset)
        self.update_visual()

    def rebind(self, default_weapon_name, weapon_list):
        """Swap to a new chassis's allowed list + default selection without
        recreating the QGraphicsItem."""
        self.weapon_list = weapon_list
        if not weapon_list:
            self.current_index = 0
            self.current_weapon = ""
            self.setPixmap(QPixmap())
            return
        self.current_index = weapon_list.index(default_weapon_name) if default_weapon_name in weapon_list else 0
        self.current_weapon = weapon_list[self.current_index]
        self.update_visual()

    def update_visual(self):
        if not self.current_weapon:
            return
        image_path = os.path.join(constants.MECH_ASSET_DIR, f"{self.current_weapon}.png")
        if os.path.exists(image_path):
            self.setPixmap(QPixmap(image_path))

    def hoverEnterEvent(self, event):
        self.setOpacity(0.6)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setOpacity(1.0)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if not self.weapon_list:
            return

        if event.button() == Qt.MouseButton.LeftButton:
            self.current_index = (self.current_index + 1) % len(self.weapon_list)
        elif event.button() == Qt.MouseButton.RightButton:
            self.current_index = (self.current_index - 1) % len(self.weapon_list)

        self.current_weapon = self.weapon_list[self.current_index]
        self.update_visual()
        self.cycle_sound.play()
        event.accept()


class ChassisItem(QGraphicsPixmapItem):
    """Clickable chassis sprite. Left-click cycles forward through CHASSIS_ORDER,
    right-click cycles backward. Calls back into the editor to swap state and
    re-render the schematic."""

    def __init__(self, editor):
        super().__init__()
        self.editor = editor

        self.cycle_sound = QSoundEffect()
        if os.path.exists(constants.SFX_CYCLE):
            self.cycle_sound.setSource(QUrl.fromLocalFile(constants.SFX_CYCLE))
            self.cycle_sound.setVolume(0.4)

        self.setAcceptHoverEvents(True)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))

    def set_chassis(self, chassis_name):
        """Swap to the named chassis's sprite. Re-anchors so the sprite stays
        centered at the scene origin (matches the old base.png behavior)."""
        image_path = os.path.join(constants.MECH_ASSET_DIR, f"{chassis_name}.png")
        if os.path.exists(image_path):
            self.setPixmap(QPixmap(image_path))
            rect = self.boundingRect()
            self.setPos(-rect.width() / 2, -rect.height() / 2)

    def hoverEnterEvent(self, event):
        self.setOpacity(0.6)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.setOpacity(1.0)
        super().hoverLeaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.editor.cycle_chassis(+1)
        elif event.button() == Qt.MouseButton.RightButton:
            self.editor.cycle_chassis(-1)
        else:
            return
        self.cycle_sound.play()
        event.accept()


# Editor widget
LEFT_HARDPOINT_OFFSET  = (25, -140)
RIGHT_HARDPOINT_OFFSET = (-100, -140)


class MechEditorWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(180, 180)

        self.available_weapons = load_weapon_manifest()
        self.loadouts = load_all_loadouts()

        cfg = functions.load_config()
        saved_active = cfg.get("active_chassis")
        self.active_chassis = saved_active if saved_active in CHASSIS_ORDER else CHASSIS_ORDER[0]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.scene = QGraphicsScene()
        self.view = QGraphicsView(self.scene)
        self.view.setStyleSheet("background-color: transparent; border: none;")
        self.view.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.view.scale(0.45, 0.45)
        layout.addWidget(self.view)

        self.chassis_item = None
        self.left_hardpoint = None
        self.right_hardpoint = None
        self.btn_save = None
        self.save_proxy = None

        self.build_schematic()

    def _allowed(self, side):
        """Intersect the allowed-for-this-arm list with what's actually in the
        weapon manifest, preserving allowed-list order (which is cycle order)."""
        return [w for w in allowed_weapons_for(self.active_chassis, side)
                if w in self.available_weapons]

    def build_schematic(self):
        self.chassis_item = ChassisItem(self)
        self.chassis_item.set_chassis(self.active_chassis)
        if self.chassis_item.pixmap().isNull():
            return
        self.scene.addItem(self.chassis_item)

        left_default = self.loadouts[self.active_chassis]["left"]
        right_default = self.loadouts[self.active_chassis]["right"]

        self.left_hardpoint = HardpointItem(
            'left', left_default, self._allowed("left"),
            *LEFT_HARDPOINT_OFFSET,
        )
        self.scene.addItem(self.left_hardpoint)

        self.right_hardpoint = HardpointItem(
            'right', right_default, self._allowed("right"),
            *RIGHT_HARDPOINT_OFFSET,
        )
        self.scene.addItem(self.right_hardpoint)

        self.btn_save = InteractiveCTA(label="SAVE", width=120, height=35, click_sound_path=constants.SFX_SAVE)
        self.btn_save.clicked.connect(self.commit_loadout)
        self.save_proxy = self.scene.addWidget(self.btn_save)

        chassis_rect = self.chassis_item.boundingRect()
        y_pos = (chassis_rect.height() / 2) - 10
        self.save_proxy.setPos(-80, y_pos)

    def refresh_schematic(self):
        """Re-render the schematic for the currently active chassis. Reuses
        existing graphics items rather than tearing the scene down."""
        if self.chassis_item is None:
            return

        self.chassis_item.set_chassis(self.active_chassis)

        left_default = self.loadouts[self.active_chassis]["left"]
        right_default = self.loadouts[self.active_chassis]["right"]

        self.left_hardpoint.rebind(left_default, self._allowed("left"))
        self.right_hardpoint.rebind(right_default, self._allowed("right"))

    def _capture_current(self):
        """Snapshot the in-scene arm selections into self.loadouts for the
        currently active chassis."""
        if self.left_hardpoint and self.right_hardpoint:
            self.loadouts[self.active_chassis] = {
                "left":  self.left_hardpoint.current_weapon,
                "right": self.right_hardpoint.current_weapon,
            }

    def cycle_chassis(self, direction):
        """Save in-memory state for the current chassis, advance, re-render."""
        self._capture_current()
        idx = CHASSIS_ORDER.index(self.active_chassis)
        self.active_chassis = CHASSIS_ORDER[(idx + direction) % len(CHASSIS_ORDER)]

        # Persist last-edited chassis so the next launcher run remembers.
        try:
            cfg = functions.load_config()
            cfg["active_chassis"] = self.active_chassis
            functions.save_config(cfg)
        except Exception as e:
            print(f"Failed to persist active chassis: {e}")

        self.refresh_schematic()

    def commit_loadout(self):
        try:
            self._capture_current()
            save_all_loadouts(self.loadouts)
            print("Exosuit Edit Successful")
        except Exception as e:
            print(f"Exosuit Edit Failed: {e}")
