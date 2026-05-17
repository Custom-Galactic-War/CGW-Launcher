import sys
import os
import time

from PyQt6 import QtGui
from PyQt6.QtWidgets import QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFileDialog, QMessageBox
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
        functions.launch_and_restore()

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

        functions.ensure_required_files_in_data()

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

        # Manual game folder override (shown when auto-detect fails or a manual
        # path has been saved). The path label sits under the button so the
        # user can always see what's currently in use.
        set_folder_layout = QHBoxLayout()
        self.btn_set_folder = InteractiveCTA(
            label="SET GAME FOLDER",
            width=200,
            height=30,
            click_sound_path=constants.SFX_SAVE,
            font_size=12,
        )
        self.btn_set_folder.clicked.connect(self.on_set_game_folder)
        set_folder_layout.addStretch()
        set_folder_layout.addWidget(self.btn_set_folder)
        set_folder_layout.addStretch()
        self.main_layout.addLayout(set_folder_layout)

        self.path_label = QLabel("")
        self.path_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.path_label.setWordWrap(True)
        self.path_label.setStyleSheet(
            f"QLabel {{ color: {constants.COLOR_TEXT_LIGHT}; "
            f"font-family: Consolas; font-size: 11px; padding: 4px 30px; }}"
        )
        self.main_layout.addWidget(self.path_label)

        self.refresh_game_folder_ui()

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
            os.path.join(os.getcwd(), "Instructions.txt"),
            os.path.join(os.getcwd(), "instructions.txt"),
            os.path.join(os.getcwd(), "data", "Instructions.txt"),
            os.path.join(os.getcwd(), "data", "instructions.txt"),
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

    def refresh_game_folder_ui(self):
        """Show the SET GAME FOLDER button + path label only when needed.
        Visible when auto-detection fails, OR when the user has saved a
        manual override (so they can change it again later)."""
        saved = functions.get_saved_bin_dir()
        auto = functions.auto_detect_helldivers_bin_dir()
        effective = saved or auto

        needs_button = (auto is None) or (saved is not None)

        if needs_button:
            self.btn_set_folder.show()
            if effective:
                source = "manual" if saved else "auto-detected"
                self.path_label.setText(
                    f"Helldivers 2 folder ({source}):\n{effective}"
                )
                self.path_label.setStyleSheet(
                    f"QLabel {{ color: {constants.COLOR_TEXT_LIGHT}; "
                    f"font-family: Consolas; font-size: 11px; padding: 4px 30px; }}"
                )
            else:
                self.path_label.setText(
                    "Helldivers 2 folder not detected — click SET GAME FOLDER above."
                )
                self.path_label.setStyleSheet(
                    f"QLabel {{ color: {constants.COLOR_TEXT_WARN}; "
                    f"font-family: Consolas; font-size: 11px; padding: 4px 30px; }}"
                )
            self.path_label.show()
        else:
            self.btn_set_folder.hide()
            self.path_label.hide()

    def on_set_game_folder(self):
        #Open a directory picker, validate the choice, save it, and refresh.
        # Suggest the current saved or auto-detected path as the starting dir.
        start_dir = functions.get_helldivers_bin_dir() or os.path.expanduser("~")

        selected = QFileDialog.getExistingDirectory(
            self,
            "Select your Helldivers 2 folder (or its 'bin' subfolder)",
            start_dir,
        )
        if not selected:
            return

        normalized = functions.normalize_helldivers_bin_dir(selected)
        if not normalized:
            QMessageBox.critical(
                self,
                "Invalid Helldivers 2 Folder",
                f"The selected folder does not look like a Helldivers 2 install.\n\n"
                f"Selected: {selected}\n\n"
                f"Please pick either the Helldivers 2 game folder (the one that "
                f"contains a 'bin' subfolder) or the 'bin' folder itself "
                f"(it must contain helldivers2.exe).",
            )
            return

        if functions.set_saved_bin_dir(normalized):
            QMessageBox.information(
                self,
                "Helldivers 2 Folder Saved",
                f"Saved Helldivers 2 folder:\n{normalized}\n\n"
                f"This path will be used for future launches. You can change "
                f"it again at any time using SET GAME FOLDER.",
            )
            # Now that we have a valid bin dir, retry recovering required files.
            functions.ensure_required_files_in_data()
            self.refresh_game_folder_ui()
        else:
            QMessageBox.critical(
                self,
                "Could Not Save Folder",
                "The selected folder is valid, but the launcher failed to write "
                "its config file. Check that the launcher's 'data' folder is "
                "writable.",
            )

    def initiate_launch(self):
        self.btn_play.hide()
        self.editor_panel.commit_loadout()
        
        self.injection_thread = InjectionThread()
        self.injection_thread.progress_update.connect(self.progress_bar.update_progress)
        self.injection_thread.sequence_complete.connect(self.launch_finished)
        self.injection_thread.start()

    def launch_finished(self, success):
        if success:
            QTimer.singleShot(2500, self.close)
        else:
            # An error message box was shown during the launch attempt.
            # Reset the launcher to its original state instead of closing.
            self.reset_launcher_ui()

    def reset_launcher_ui(self):
        """Restore the launcher to the same state it had at startup."""
        self.progress_bar.update_progress(0.0, "AWAITING ORDERS...")
        self.btn_play.show()
        # The user may have just fixed (or now needs to set) the game folder,
        # so refresh that part of the UI too.
        self.refresh_game_folder_ui()

    def closeEvent(self, event):
        if hasattr(self, 'rpc_manager'):
            self.rpc_manager.stop()
            self.rpc_manager.wait()
        functions.ensure_required_files_in_data()
        self.rpc_manager.stop()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app_icon = QtGui.QIcon()
    app_icon.addFile('data/assets/icon.png', QSize(256, 256))
    app.setWindowIcon(app_icon)
    window = CustomGalacticWarLauncher()
    window.show()
    sys.exit(app.exec())