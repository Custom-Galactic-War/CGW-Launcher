import sys
import os
import time

from PyQt6 import QtGui
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QMessageBox, QInputDialog
from PyQt6.QtGui import QPixmap, QPainter, QColor
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QUrl, QTimer, QSize

import constants
import functions 
from button_cta import InteractiveCTA
from mech_editor import MechEditorWidget
from custom_widgets import LinkButtonWidget, LauncherProgressBar, IconButton, InstructionsOverlay
from discord_rpc import DiscordRPCManager

class InjectionThread(QThread):
    progress_update = pyqtSignal(float, str)
    sequence_complete = pyqtSignal(bool)  # True == clean run, no error popups

    def run(self):
        functions.reset_error_count()

        self.progress_update.emit(10.0, "INITIALIZING...")
        time.sleep(1.0)
        self.progress_update.emit(50.0, "LAUNCHING HELLPODS... DO NOT CLOSE THIS WINDOW!")
        functions.launch_game()

        success = functions.error_count_since_reset() == 0
        if success:
            self.progress_update.emit(100.0, "FIGHT FOR MANAGED DEMOCRACY!")
            time.sleep(1.0)
        self.sequence_complete.emit(success)


class CustomGalacticWarLauncher(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("E-710 Launcher")
        self.setFixedSize(900, 500) 
        
        # Eats the title bar
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint)
        self.setStyleSheet(f"QMainWindow {{ border: 2px solid {constants.COLOR_PRIMARY}; background-color: {constants.COLOR_BG_DARKER}; }}")

        # Pull any files a previous session stranded in 'bin' back into the
        # 'files' folder before the UI (and the mech editor) load.
        functions.ensure_required_files_in_files()

        self.setup_ui()

        # Discord RPC
        self.rpc_manager = DiscordRPCManager("1440833019962327231")
        self.rpc_manager.start()

    def setup_ui(self):
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.main_layout = QVBoxLayout(self.central_widget)
        self.main_layout.setContentsMargins(40, 40, 40, 30)

        # Adds the logo
        self.logo_label = QLabel()
        if os.path.exists(constants.LOGO_PATH):
            pix = QPixmap(constants.LOGO_PATH).scaledToHeight(120, Qt.TransformationMode.SmoothTransformation)
            self.logo_label.setPixmap(pix)
            
        self.logo_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop)
        self.main_layout.addWidget(self.logo_label)
        self.main_layout.addStretch()

        # Builds the CONNECT button
        btn_layout = QHBoxLayout()
        self.btn_play = InteractiveCTA(label="CONNECT", width=220, height=50, click_sound_path=constants.SFX_SAVE)
        self.btn_play.clicked.connect(self.initiate_launch)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_play)
        btn_layout.addStretch()
        self.main_layout.addLayout(btn_layout)

        # SHARE LOBBY button — lets the user paste a Steam join-lobby URL and
        # push it into Discord Rich Presence so friends can join via the
        # "Join Lobby" button on the launcher's Discord card. Toggles between
        # SHARE LOBBY and STOP SHARING based on whether a lobby is active.
        share_layout = QHBoxLayout()
        self.btn_share_lobby = InteractiveCTA(
            label="SHARE LOBBY",
            width=200,
            height=30,
            click_sound_path=constants.SFX_SAVE,
            font_size=12,
        )
        self.btn_share_lobby.clicked.connect(self.on_share_lobby)
        share_layout.addStretch()
        share_layout.addWidget(self.btn_share_lobby)
        share_layout.addStretch()
        self.main_layout.addLayout(share_layout)

        self.lobby_label = QLabel("")
        self.lobby_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lobby_label.setWordWrap(True)
        self.lobby_label.setStyleSheet(
            f"QLabel {{ color: {constants.COLOR_TEXT_LIGHT}; "
            f"font-family: Consolas, monospace; font-size: 11px; padding: 4px 30px; }}"
        )
        self.lobby_label.hide()
        self.main_layout.addWidget(self.lobby_label)

        # Tracks the currently-shared lobby (the "<lobby_id>/<host_id>" tail).
        # None means "not sharing"; any string means the button shows STOP
        # SHARING and the Discord presence is "Hosting Lobby".
        self._current_lobby_tail = None

        self.main_layout.addStretch()

        # Builds the progbar
        self.progress_bar = LauncherProgressBar()
        self.progress_bar.start_anim()
        self.main_layout.addWidget(self.progress_bar)

        # Builds mech editor
        self.editor_panel = MechEditorWidget(self.central_widget)
        self.editor_panel.move(710, 10) 
        self.editor_panel.raise_() 
        
        discord_icon_path = os.path.join(constants.ASSET_DIR, "discord.png")
        self.link_button = LinkButtonWidget(discord_icon_path, "https://discord.gg/cgw", self.central_widget)
        self.link_button.move(10, 10)
        self.link_button.raise_()

        # Info icon under the Discord icon — opens the Instructions overlay.
        info_icon_path = os.path.join(constants.ASSET_DIR, "info.png")
        self.info_button = IconButton(
            icon_path=info_icon_path,
            fallback_letter="i",
            tooltip="Show instructions",
            size=35,
            parent=self.central_widget,
        )
        self.info_button.move(10, 55)
        self.info_button.raise_()
        self.info_button.clicked.connect(self.show_instructions)

        # Auto-show instructions the first time the launcher is opened.
        QTimer.singleShot(0, self.maybe_auto_show_instructions)

    def paintEvent(self, event):
        super().paintEvent(event)
        if os.path.exists(constants.BG_PATH):
            painter = QPainter(self)
            pix = QPixmap(constants.BG_PATH)
            scaled_pix = pix.scaled(self.width(), self.height(), Qt.AspectRatioMode.KeepAspectRatioByExpanding, Qt.TransformationMode.SmoothTransformation)
            painter.drawPixmap(0, 0, scaled_pix)
            painter.fillRect(self.rect(), QColor(0, 0, 0, 150))

    def load_instructions_text(self):
        """Locate and read Instructions.txt. Returns a placeholder if missing."""
        candidates = [
            os.path.join(constants.BASE_DIR, "Instructions.txt"),
            os.path.join(constants.BASE_DIR, "instructions.txt"),
            os.path.join(constants.FILES_DIR, "Instructions.txt"),
            os.path.join(constants.FILES_DIR, "instructions.txt"),
        ]
        for path in candidates:
            if os.path.isfile(path):
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as f:
                        return f.read()
                except Exception as e:
                    return (
                        f"# Could not read instructions\n\n"
                        f"Failed to open {path}:\n\n{e}"
                    )
        return (
            "# Instructions Not Found\n\n"
            "The launcher could not find an 'Instructions.txt' file next to the "
            "launcher executable.\n\n"
            "Please make sure 'Instructions.txt' is in the launcher's folder."
        )

    def show_instructions(self):
        # Avoid stacking overlays if one is already up.
        if getattr(self, "_instructions_overlay", None) is not None:
            return
        overlay = InstructionsOverlay(self.load_instructions_text(), parent=self.central_widget)
        overlay.setGeometry(0, 0, self.central_widget.width(), self.central_widget.height())
        overlay.closed.connect(self._on_instructions_closed)
        overlay.show()
        overlay.raise_()
        overlay.setFocus()
        self._instructions_overlay = overlay

    def _on_instructions_closed(self):
        self._instructions_overlay = None

    def maybe_auto_show_instructions(self):
        cfg = functions.load_config()
        if cfg.get("seen_instructions"):
            return
        self.show_instructions()
        cfg["seen_instructions"] = True
        functions.save_config(cfg)

    def on_share_lobby(self):
        """Toggle Discord lobby sharing. When not sharing, opens a paste dialog
        and validates the URL. When already sharing, clears the lobby and
        resets Discord presence to idle."""
        if self._current_lobby_tail is not None:
            # Already sharing — stop.
            self.rpc_manager.clear_lobby()
            self._current_lobby_tail = None
            self._refresh_lobby_ui()
            return

        instructions = (
            "Paste your Steam lobby link below.\n\n"
            "How to get it:\n"
            "  1. In Steam, click your name (top right) -> View My Profile.\n"
            "  2. Find the 'Currently In-Game' section showing Helldivers 2.\n"
            "  3. Right-click the 'Join Game' button -> Copy Link Address.\n"
            "  4. Paste the link here.\n\n"
            "Expected format:\n"
            "steam://joinlobby/553850/<lobby_id>/<your_steam_id>"
        )
        text, ok = QInputDialog.getText(self, "Share Helldivers 2 Lobby", instructions)
        if not ok:
            return

        _, tail = functions.parse_lobby_url(text)
        if not tail:
            QMessageBox.warning(
                self,
                "Invalid Lobby Link",
                "That didn't look like a Helldivers 2 lobby link.\n\n"
                "Expected format:\n"
                "steam://joinlobby/553850/<lobby_id>/<your_steam_id>\n\n"
                "Make sure you copied the link from Steam's right-click menu "
                "on the 'Join Game' button, and that the game is Helldivers 2 "
                "(appid 553850).",
            )
            return

        self.rpc_manager.set_lobby(tail, constants.LOBBY_REDIRECT_BASE)
        self._current_lobby_tail = tail
        self._refresh_lobby_ui()

    def _refresh_lobby_ui(self):
        """Sync the SHARE LOBBY button label and the status line with the
        current sharing state."""
        if self._current_lobby_tail:
            self.btn_share_lobby.set_label("STOP SHARING")
            self.lobby_label.setText(f"Sharing lobby: {self._current_lobby_tail}")
            self.lobby_label.show()
        else:
            self.btn_share_lobby.set_label("SHARE LOBBY")
            self.lobby_label.setText("")
            self.lobby_label.hide()

    def initiate_launch(self):
        # Any currently-shared lobby URL is about to become stale (relaunching
        # the game tears down the existing lobby). Clear it so the Discord
        # presence doesn't keep advertising a lobby that no longer exists.
        if self._current_lobby_tail is not None:
            self.rpc_manager.clear_lobby()
            self._current_lobby_tail = None
            self._refresh_lobby_ui()

        self.btn_play.hide()
        self.editor_panel.commit_loadout()

        self.injection_thread = InjectionThread()
        self.injection_thread.progress_update.connect(self.progress_bar.update_progress)
        self.injection_thread.sequence_complete.connect(self.launch_finished)
        self.injection_thread.start()

    def launch_finished(self, success):
        if success:
            # Keep the "FIGHT FOR MANAGED DEMOCRACY!" message visible briefly,
            # then return the launcher to its starting state so the user can
            # connect again without re-opening it.
            QTimer.singleShot(2500, self.reset_launcher_ui)
        else:
            # An error message box was shown during the launch attempt.
            # Reset the launcher to its original state instead of closing.
            self.reset_launcher_ui()

    def reset_launcher_ui(self):
        """Restore the launcher to the same state it had at startup."""
        self.progress_bar.update_progress(0.0, "AWAITING ORDERS...")
        self.btn_play.show()

    def closeEvent(self, event):
        # Wait for the injection thread to finish so the files it moved into
        # 'bin' get pulled back into the 'files' folder. The 55s ceiling
        # covers the 45s game-init wait plus a buffer. Closing mid-injection
        # is a safety net, not a graceful cancel.
        if hasattr(self, 'injection_thread') and self.injection_thread.isRunning():
            self.injection_thread.wait(55000)

        if hasattr(self, 'rpc_manager'):
            self.rpc_manager.stop()
            self.rpc_manager.wait()
        # Final safety net: pull anything still in 'bin' back into 'files'.
        functions.ensure_required_files_in_files()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app_icon = QtGui.QIcon()
    app_icon.addFile(os.path.join(constants.ASSET_DIR, "icon.png"), QSize(256, 256))
    app.setWindowIcon(app_icon)
    window = CustomGalacticWarLauncher()
    window.show()
    sys.exit(app.exec())