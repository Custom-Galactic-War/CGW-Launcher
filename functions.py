import os
import platform
import re
import shutil
import string
import subprocess
import time
import json
import tkinter as tk
from tkinter import messagebox

try:
    import winreg
except ImportError:
    winreg = None

import constants

_IS_WINDOWS = platform.system() == "Windows"

# The launcher's own config file lives in the 'files' folder shipped alongside
# the launcher (it is a launcher-internal file, never injected into the game).
CONFIG_FILE = os.path.join(constants.FILES_DIR, 'launcher_config.json')


def load_config():
    try:
        if os.path.isfile(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"Failed to load launcher config: {e}")
    return {}


def save_config(cfg):
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
            json.dump(cfg, f, indent=4)
        return True
    except Exception as e:
        print(f"Failed to save launcher config: {e}")
        return False


# Matches the Helldivers 2 Steam join-lobby URL format.
# steam://joinlobby/553850/<lobby_id>/<host_steam_id>
# Hardcoded to Helldivers 2's appid (553850) so pastes from other Steam games
# don't accidentally get accepted.
_STEAM_LOBBY_RE = re.compile(
    r"steam://joinlobby/553850/(\d+)/(\d+)\b",
    re.IGNORECASE,
)


# Parse a Steam join-lobby URL out of arbitrary pasted text. Returns
# (canonical_url, tail) where `tail` is the "<lobby_id>/<host_steam_id>"
# portion (used to build the GitHub-Pages redirect URL). Returns (None, None)
# if the input doesn't contain a recognizable Helldivers 2 lobby URL.
def parse_lobby_url(text):
    if not text:
        return None, None
    match = _STEAM_LOBBY_RE.search(text.strip())
    if not match:
        return None, None
    lobby_id, host_id = match.group(1), match.group(2)
    canonical = f"steam://joinlobby/553850/{lobby_id}/{host_id}"
    tail = f"{lobby_id}/{host_id}"
    return canonical, tail


# Module-level counter for error message boxes shown since the last reset.
# The launcher UI uses this to detect whether the most recent launch attempt
# triggered any errors so it can reset itself instead of closing.
_error_count = 0


def reset_error_count():
    global _error_count
    _error_count = 0


def error_count_since_reset():
    return _error_count


# Show a modal error dialog. Falls back to console output if Tk is unavailable.
# Every call increments the error counter so the launcher knows an error was
# surfaced to the user during the current operation.
def show_error_box(title, message):
    global _error_count
    _error_count += 1
    print(f"[{title}] {message}")
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showerror(title, message, parent=root)
        root.destroy()
    except Exception as e:
        print(f"(Could not display message box: {e})")


# Standardized warning for the "files missing from BOTH locations" scenario.
def show_antivirus_warning(missing_files):
    if isinstance(missing_files, str):
        missing_files = [missing_files]
    files_list = "\n  - ".join(missing_files)
    show_error_box(
        "Launcher Files Missing - Possible Anti-Virus Deletion",
        "The following file(s) could not be found in either the launcher's "
        "'files' folder or the Helldivers 2 'bin' folder:\n\n"
        f"  - {files_list}\n\n"
        "They were most likely deleted by your anti-virus software due to a "
        "false positive detection.\n\n"
        "Please check your anti-virus quarantine, restore the file(s), and add "
        "the launcher's folder to your anti-virus exclusions list before "
        "launching again."
    )


# Well-known Steam install locations on Linux (native + Flatpak). Most of the
# `~/.steam/*` paths are symlinks that resolve to one of the others; we
# de-duplicate via os.path.realpath when iterating.
_LINUX_STEAM_INSTALL_CANDIDATES = (
    "~/.local/share/Steam",
    "~/.steam/steam",
    "~/.steam/root",
    "~/.steam/debian-installation",
    "~/.var/app/com.valvesoftware.Steam/.local/share/Steam",
)


# Yields candidate directories that might contain a Steam install. On Windows
# this is every accessible drive letter (used to brute-force common install
# layouts). On Linux it's the user's home plus common external mount points
# (/mnt, /media, /run/media/<user>) plus their immediate children.
def _drive_search_roots():
    if _IS_WINDOWS:
        for case in (string.ascii_uppercase, string.ascii_lowercase):
            for letter in case:
                drive = f"{letter}:\\"
                if os.path.exists(drive):
                    yield drive
        return

    user = os.environ.get("USER") or os.environ.get("LOGNAME") or ""
    roots = [
        os.path.expanduser("~"),
        "/mnt",
        "/media",
    ]
    if user:
        roots.extend([f"/media/{user}", f"/run/media/{user}"])

    seen = set()
    for root in roots:
        if not root or not os.path.isdir(root):
            continue
        real = os.path.realpath(root)
        if real in seen:
            continue
        seen.add(real)
        yield root + os.sep
        try:
            for entry in os.listdir(root):
                full = os.path.join(root, entry)
                if os.path.isdir(full):
                    real_sub = os.path.realpath(full)
                    if real_sub in seen:
                        continue
                    seen.add(real_sub)
                    yield full + os.sep
        except (OSError, PermissionError):
            continue


# Returns the argv list needed to invoke Steam, or None. On Windows this is
# `[steam.exe]`. On Linux it's either `[/usr/bin/steam]` (native install) or
# `["flatpak", "run", "com.valvesoftware.Steam"]` (Flatpak install).
def find_steam_launch_argv():
    if _IS_WINDOWS:
        path = find_steam_exe()
        return [path] if path else None

    # Native Linux Steam — prefer whatever's on PATH.
    found = shutil.which("steam")
    if found:
        return [found]

    native_paths = [
        "/usr/bin/steam",
        "/usr/games/steam",
        "/usr/local/bin/steam",
        os.path.expanduser("~/.local/bin/steam"),
        os.path.expanduser("~/.steam/steam.sh"),
    ]
    for p in native_paths:
        if os.path.isfile(p) and os.access(p, os.X_OK):
            return [p]

    # Flatpak Steam — the binary isn't directly on PATH, but `flatpak run` is.
    flatpak = shutil.which("flatpak")
    if flatpak:
        flatpak_install_dirs = (
            os.path.expanduser("~/.var/app/com.valvesoftware.Steam"),
            "/var/lib/flatpak/app/com.valvesoftware.Steam",
        )
        if any(os.path.isdir(d) for d in flatpak_install_dirs):
            return [flatpak, "run", "com.valvesoftware.Steam"]

    return None


# Locate the Steam launcher binary (steam.exe on Windows, `steam` on Linux).
# Returns a single path string for native installs. Returns None on Linux if
# only a Flatpak install is available (callers should use find_steam_launch_argv
# for the actual invocation).
def find_steam_exe():
    if _IS_WINDOWS:
        install_path = find_steam_install_path()
        if install_path:
            candidate = os.path.join(install_path, "steam.exe")
            if os.path.isfile(candidate):
                return candidate

        if winreg is not None:
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as key:
                    value, _ = winreg.QueryValueEx(key, "SteamExe")
                    if value and os.path.isfile(value):
                        return value
            except OSError:
                pass

        fallback_paths = [
            r"Program Files (x86)\Steam\steam.exe",
            r"Program Files\Steam\steam.exe",
        ]
        for drive in _drive_search_roots():
            for subpath in fallback_paths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isfile(potential_path):
                    return potential_path

        found = shutil.which("steam.exe") or shutil.which("steam")
        if found:
            return found
        return None

    # Linux: prefer the `steam` binary on PATH, then well-known native paths.
    found = shutil.which("steam")
    if found:
        return found
    for path in (
        "/usr/bin/steam",
        "/usr/games/steam",
        "/usr/local/bin/steam",
        os.path.expanduser("~/.local/bin/steam"),
        os.path.expanduser("~/.steam/steam.sh"),
    ):
        if os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


# Locate the Steam install directory itself (not the launcher binary).
def find_steam_install_path():
    if _IS_WINDOWS:
        if winreg is not None:
            reg_locations = [
                (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam", "InstallPath"),
            ]
            for hive, subkey, value_name in reg_locations:
                try:
                    with winreg.OpenKey(hive, subkey) as key:
                        value, _ = winreg.QueryValueEx(key, value_name)
                        if value and os.path.isdir(value):
                            return os.path.normpath(value)
                except OSError:
                    continue

        fallback_paths = [
            r"Program Files (x86)\Steam",
            r"Program Files\Steam",
        ]
        for drive in _drive_search_roots():
            for subpath in fallback_paths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isdir(potential_path):
                    return potential_path
        return None

    # Linux: well-known native + Flatpak install locations. Several entries
    # are symlinks pointing at the same place, so de-dupe via realpath.
    seen = set()
    for raw in _LINUX_STEAM_INSTALL_CANDIDATES:
        expanded = os.path.expanduser(raw)
        if not os.path.isdir(expanded):
            continue
        real = os.path.realpath(expanded)
        if real in seen:
            continue
        seen.add(real)
        # Sanity check — a real Steam install has a steamapps subfolder.
        if os.path.isdir(os.path.join(real, "steamapps")):
            return real
    return None


# Standard game files that must exist in the Helldivers 2 'bin' folder for
# the modded launch to work. Anti-virus software occasionally deletes these
# (especially the msvcp140 DLLs) — hence the pre-launch presence check.
REQUIRED_BIN_FILENAMES = ("discord_game_sdk.dll", "mounts.json", "msvcp140.dll", "msvcp140_real.dll")

# Anchor file that confirms a folder really is the Helldivers 2 'bin' folder.
HELLDIVERS_EXE_FILENAME = "helldivers2.exe"

# Files in 'files/' that belong to the launcher itself, not the game. They
# must never be moved into the game's 'bin' folder. Compared case-insensitively.
LAUNCHER_ONLY_FILENAMES = frozenset({
    "launcher_config.json",
    "exosuit_weapons.json",
    "instructions.txt",
})


# Returns True if a helldivers2.exe process is currently running. Used to
# block CONNECT clicks while the game is already open — moving files into the
# bin folder while the game has them mapped is a recipe for corrupted state.
# The helldivers2.exe name is the same on Linux Proton (Wine runs it under the
# same process name), so the same check works on both platforms.
def is_helldivers_running():
    target = HELLDIVERS_EXE_FILENAME.lower()

    if _IS_WINDOWS:
        try:
            # CREATE_NO_WINDOW (0x08000000) hides the conhost flash that
            # tasklist would otherwise produce when called from a GUI app.
            # stdin is redirected because a --windowed PyInstaller build has
            # no console; an inherited invalid stdin handle makes subprocess
            # raise.
            result = subprocess.run(
                ["tasklist", "/FI", f"IMAGENAME eq {HELLDIVERS_EXE_FILENAME}", "/NH"],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=5,
                creationflags=0x08000000,
            )
        except (OSError, subprocess.SubprocessError):
            return False
        return target in result.stdout.lower()

    # Linux: scan /proc for any process whose executable basename matches.
    # On Linux/Proton the game runs as helldivers2.exe inside Wine, so the
    # /proc/<pid>/comm value is "helldivers2.exe" (truncated to 15 chars on
    # older kernels — still matches our substring check).
    proc_root = "/proc"
    if not os.path.isdir(proc_root):
        return False
    try:
        entries = os.listdir(proc_root)
    except OSError:
        return False
    for entry in entries:
        if not entry.isdigit():
            continue
        comm_path = os.path.join(proc_root, entry, "comm")
        try:
            with open(comm_path, "r", encoding="utf-8", errors="ignore") as f:
                comm = f.read().strip().lower()
        except (OSError, IOError):
            continue
        # /proc/<pid>/comm truncates to 15 chars on some kernels, so we
        # match a prefix of the target rather than equality.
        if comm and (comm == target or target.startswith(comm)):
            return True
    return False


# Returns the mounts.json the mech editor should read and write. If the bin
# folder already has one, that's the live copy the game loads, so edits go
# straight to it; otherwise edits go to the copy in the 'files' folder.
def get_active_mounts_json_path():
    bin_mounts = os.path.join(constants.BIN_DIR, "mounts.json")
    if os.path.isfile(bin_mounts):
        return bin_mounts
    return os.path.join(constants.FILES_DIR, "mounts.json")


# Returns a sorted list of required files that are missing from BOTH the
# 'files' folder and the 'bin' folder. An empty list means everything needed
# is present in at least one of the two locations.
def check_required_files():
    missing = []
    for name in REQUIRED_BIN_FILENAMES:
        in_files = os.path.isfile(os.path.join(constants.FILES_DIR, name))
        in_bin = os.path.isfile(os.path.join(constants.BIN_DIR, name))
        if not in_files and not in_bin:
            missing.append(name)
    return sorted(missing)


# Moves the launcher's game files from the local 'files' folder into the local
# 'bin' folder. Existing copies in 'bin' are overwritten. Returns the list of
# filenames that were moved so launch_game can move them back afterwards.
# Two files are special-cased and NOT tracked for return:
#   - dxgi.dll: only injected when 'bin' already has one (ReShade).
#   - mounts.json: skipped when 'bin' already has one; when 'bin' has none it
#     is moved in but then left there (it holds the player's mech loadout).
# Surfaces an error popup and stops at the first failure.
def move_files_to_bin():
    source_dir = constants.FILES_DIR
    target_dir = constants.BIN_DIR
    moved_files = []

    if not os.path.isdir(source_dir):
        show_error_box(
            "Launcher 'files' Folder Not Found",
            f"The launcher's 'files' folder was not found at:\n{source_dir}\n\n"
            "It may have been deleted by anti-virus software, or the launcher "
            "may have been moved without its 'files' folder."
        )
        return moved_files

    print("Moving files into the Helldivers 2 'bin' folder...")

    for filename in os.listdir(source_dir):
        source_path = os.path.join(source_dir, filename)
        target_path = os.path.join(target_dir, filename)

        # Only top-level files get injected — skip subfolders (assets/, etc.).
        if not os.path.isfile(source_path):
            continue

        # Launcher-internal files stay in 'files/'.
        if filename.lower() in LAUNCHER_ONLY_FILENAMES:
            continue

        # mounts.json: if the bin folder already has one, leave it untouched
        # — it holds the player's mech loadout and must not be overwritten.
        if filename.lower() == "mounts.json" and os.path.isfile(target_path):
            print(" -> Skipped: mounts.json (already in bin; left as-is)")
            continue

        # dxgi.dll: only inject when the bin folder already has a dxgi.dll
        # (i.e. ReShade is installed); otherwise it isn't wanted.
        if filename.lower() == "dxgi.dll" and not os.path.isfile(target_path):
            print(" -> Skipped: dxgi.dll (no existing dxgi.dll in bin)")
            continue

        try:
            # Overwrite any existing copy already in the bin folder.
            if os.path.exists(target_path):
                os.remove(target_path)
            shutil.move(source_path, target_path)
            # dxgi.dll (ReShade's own file) and mounts.json (the mech loadout)
            # stay in 'bin' once injected — only the rest is tracked so it can
            # be restored after the game has loaded it.
            if filename.lower() not in ("dxgi.dll", "mounts.json"):
                moved_files.append(filename)
            print(f" -> Injected: {filename}")
        except Exception as e:
            show_error_box(
                "Failed to Move File to Helldivers 2",
                f"Could not move '{filename}' into:\n{target_dir}\n\n"
                f"Error: {e}\n\n"
                "This is usually caused by anti-virus software locking the "
                "file. Try adding both the launcher folder and the "
                "Helldivers 2 'bin' folder to your anti-virus exclusions list."
            )
            # Stop at the first failure.
            break

    return moved_files


# Moves the given files from the 'bin' folder back into the launcher's 'files'
# folder. Run after a launch (once the game has loaded the injected files) so
# the game's 'bin' folder is left clean.
def move_files_back_to_files(files_to_retrieve):
    source_dir = constants.BIN_DIR
    target_dir = constants.FILES_DIR

    print("\nReturning files to the launcher's 'files' folder...")
    moved_count = 0
    missing_files = []
    failed_moves = []

    for filename in files_to_retrieve:
        source_path = os.path.join(source_dir, filename)
        target_path = os.path.join(target_dir, filename)

        if os.path.isfile(source_path):
            try:
                if os.path.exists(target_path):
                    os.remove(target_path)
                shutil.move(source_path, target_path)
                print(f" -> Retrieved: {filename}")
                moved_count += 1
            except Exception as e:
                print(f" -> Error returning '{filename}': {e}")
                failed_moves.append((filename, str(e)))
        elif not os.path.isfile(target_path):
            # Missing from BOTH the bin folder and the files folder.
            missing_files.append(filename)

    if missing_files:
        show_antivirus_warning(missing_files)

    if failed_moves:
        details = "\n".join(f"  - {n}: {err}" for n, err in failed_moves)
        show_error_box(
            "Failed to Restore File(s) to 'files' Folder",
            "The following file(s) could not be moved back from the "
            "Helldivers 2 'bin' folder to the launcher's 'files' folder:\n\n"
            f"{details}\n\n"
            "This is usually caused by anti-virus interference. Try adding "
            "both folders to your anti-virus exclusions list."
        )

    print(f"Successfully retrieved {moved_count}/{len(files_to_retrieve)} files.")


# Safety net run when the launcher opens and closes: if a required file is
# missing from the 'files' folder, pull it back from the 'bin' folder (e.g. a
# previous session was closed before the post-launch move-back finished).
# mounts.json is excluded — once injected it is meant to stay in 'bin'.
def ensure_required_files_in_files():
    files_dir = constants.FILES_DIR
    os.makedirs(files_dir, exist_ok=True)

    # mounts.json is deliberately skipped: once it's in 'bin' it stays there
    # (it holds the player's mech loadout), so it must never be pulled back.
    missing = [
        name for name in REQUIRED_BIN_FILENAMES
        if name.lower() != "mounts.json"
        and not os.path.isfile(os.path.join(files_dir, name))
    ]
    if not missing:
        return

    truly_missing = []
    failed_recoveries = []
    for filename in missing:
        source_path = os.path.join(constants.BIN_DIR, filename)
        target_path = os.path.join(files_dir, filename)
        if os.path.isfile(source_path):
            try:
                shutil.move(source_path, target_path)
                print(f" -> Recovered: {filename}")
            except Exception as e:
                print(f" -> Error recovering '{filename}': {e}")
                failed_recoveries.append((filename, str(e)))
        else:
            truly_missing.append(filename)

    if truly_missing:
        show_antivirus_warning(truly_missing)

    if failed_recoveries:
        details = "\n".join(f"  - {n}: {err}" for n, err in failed_recoveries)
        show_error_box(
            "Failed to Recover Launcher File(s)",
            "The following file(s) were found in the Helldivers 2 'bin' folder "
            "but could not be moved back into the launcher's 'files' "
            f"folder:\n\n{details}\n\n"
            "Try adding both folders to your anti-virus exclusions list."
        )


# Verifies the game folder, injects the launcher's files into 'bin', launches
# Helldivers 2 through Steam, waits for the game to initialise, then moves the
# injected files back into the 'files' folder. Any error surfaces a popup
# (tracked via the error counter); files already moved into 'bin' are rolled
# back before the sequence aborts.
def launch_game():
    print("Starting CGW")

    # 1. Block if HD2 is already open — injecting while the game has its bin
    #    files mapped risks corrupting the live mod state.
    if is_helldivers_running():
        show_error_box(
            "Helldivers 2 Already Running",
            "Helldivers 2 is already open.\n\n"
            "Please close the game completely before clicking CONNECT, "
            "otherwise the launcher cannot inject its files safely.\n\n"
            "The launcher will not modify any files on this attempt."
        )
        return

    # 2. The launcher must sit inside the Helldivers 2 folder, next to the
    #    game's 'bin' subfolder. Verify it exists and contains helldivers2.exe.
    if not os.path.isdir(constants.BIN_DIR):
        show_error_box(
            "Helldivers 2 'bin' Folder Not Found",
            "No 'bin' folder was found next to the launcher:\n"
            f"{constants.BIN_DIR}\n\n"
            "Place the launcher and its 'files' folder directly inside your "
            "'Helldivers 2' folder (the folder that contains 'bin'), then try "
            "again."
        )
        return

    exe_path = os.path.join(constants.BIN_DIR, HELLDIVERS_EXE_FILENAME)
    if not os.path.isfile(exe_path):
        show_error_box(
            "helldivers2.exe Not Found",
            "A 'bin' folder was found next to the launcher, but it does not "
            f"contain {HELLDIVERS_EXE_FILENAME}:\n{constants.BIN_DIR}\n\n"
            "Make sure the launcher and its 'files' folder are placed directly "
            "inside your real 'Helldivers 2' game folder."
        )
        return

    # 3. Every required file must exist in EITHER 'files/' or 'bin/'.
    missing = check_required_files()
    if missing:
        show_antivirus_warning(missing)
        return

    # 4. Inject: move the game files from 'files/' into 'bin/'.
    errors_before = error_count_since_reset()
    moved_files = move_files_to_bin()
    if error_count_since_reset() > errors_before:
        # An error popup was shown during injection. Roll back whatever was
        # moved so nothing is stranded, then abort.
        if moved_files:
            print("Errors during injection. Restoring files to 'files'...")
            move_files_back_to_files(moved_files)
        return

    # 5. Launch Helldivers 2 through Steam.
    steam_argv = find_steam_launch_argv()
    if not steam_argv:
        show_error_box(
            "Steam Not Found",
            "Could not locate Steam. Please make sure Steam is installed "
            "(native or Flatpak on Linux).\n\n"
            "The launcher will restore its files and stop."
        )
        move_files_back_to_files(moved_files)
        return

    print("\nLaunching helldivers2.exe through Steam...")
    game_app_id = "553850"
    try:
        # stdin/stdout/stderr MUST be redirected to DEVNULL: a --windowed
        # PyInstaller build has no console, so the launcher's own standard
        # handles are invalid. If the child process inherits them, subprocess
        # raises and the launcher crashes. Redirecting avoids the inheritance.
        subprocess.Popen(
            [*steam_argv, "-applaunch", game_app_id],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as e:
        show_error_box(
            "Failed to Launch Helldivers 2",
            f"Could not start the game via Steam.\n\nError: {e}\n\n"
            "The launcher will restore its files and stop."
        )
        move_files_back_to_files(moved_files)
        return

    # 6. Give the game time to start up and load the injected files, then move
    #    them back out so the 'bin' folder is left clean.
    print("Waiting 45 seconds for game initialization...")
    time.sleep(45)

    move_files_back_to_files(moved_files)
    print("Successfully launched game and moved files back.")
