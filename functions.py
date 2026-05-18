import os
import re
import shutil
import string
import subprocess
import time
import json
import tkinter as tk
from sys import platform
from tkinter import messagebox, filedialog

try:
    import winreg
except ImportError:
    winreg = None

CONFIG_FILE = os.path.join(os.getcwd(), 'data', 'launcher_config.json')

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


# Returns the user's saved Helldivers 2 bin path, or None if not set / invalid.
def get_saved_bin_dir():
    path = load_config().get('helldivers_bin_dir')
    if path and os.path.isdir(path):
        return os.path.normpath(path)
    return None


# Persists a manual Helldivers 2 bin path. Returns True on success.
def set_saved_bin_dir(path):
    cfg = load_config()
    cfg['helldivers_bin_dir'] = os.path.normpath(path)
    return save_config(cfg)


# Removes the saved manual override.
def clear_saved_bin_dir():
    cfg = load_config()
    if 'helldivers_bin_dir' in cfg:
        cfg.pop('helldivers_bin_dir', None)
        return save_config(cfg)
    return True


# Accepts a user-selected folder and resolves it to a usable Helldivers 2 bin
# folder. The user may pick either the 'bin' folder itself or the game's root
# folder (which contains a 'bin' subfolder). Returns None if the selection
# isn't a valid directory.
def normalize_helldivers_bin_dir(selected_path):
    if not selected_path or not os.path.isdir(selected_path):
        return None
    bin_subfolder = os.path.join(selected_path, "bin")
    if os.path.isdir(bin_subfolder):
        return os.path.normpath(bin_subfolder)
    return os.path.normpath(selected_path)


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
        "'data' folder or the Helldivers 2 'bin' folder:\n\n"
        f"  - {files_list}\n\n"
        "They were most likely deleted by your anti-virus software due to a "
        "false positive detection.\n\n"
        "Please check your anti-virus quarantine, restore the file(s), and add "
        "the launcher's folder to your anti-virus exclusions list before "
        "launching again."
    )


# Locate steam.exe by checking the Windows registry, then common install paths.
def find_steam_exe():
    install_path = find_steam_install_path()
    if install_path:
        candidate = os.path.join(install_path, "steam.exe")
        if os.path.isfile(candidate):
            return candidate
        candidate = os.path.join(install_path, "steam")
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

    for drive_letter in string.ascii_uppercase:
        drive = f"{drive_letter}:\\"
        if os.path.exists(drive):
            for subpath in fallback_paths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isfile(potential_path):
                    return potential_path

    for drive_letter in string.ascii_lowercase:
        drive = f"{drive_letter}:\\"
        if os.path.exists(drive):
            for subpath in fallback_paths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isfile(potential_path):
                    return potential_path

    found = shutil.which("steam.exe") or shutil.which("steam")
    if found:
        return found

    return None


# Locate the Steam install directory itself (not steam.exe).
def find_steam_install_path():
    if platform == "linux" or platform == "linux2":
        return "/usr/bin/"
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

    for drive_letter in string.ascii_uppercase:
        drive = f"{drive_letter}:\\"
        if os.path.exists(drive):
            for subpath in fallback_paths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isdir(potential_path):
                    return potential_path

    for drive_letter in string.ascii_lowercase:
        drive = f"{drive_letter}:\\"
        if os.path.exists(drive):
            for subpath in fallback_paths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isdir(potential_path):
                    return potential_path

    return None


# Parse Steam's libraryfolders.vdf to discover every Steam library across all drives.
def get_steam_library_folders():
    libraries = []
    steam_path = find_steam_install_path()
    if not steam_path:
        return libraries

    libraries.append(steam_path)

    if platform == "linux" or platform == "linux2":
        steam_path = os.path.join(os.getenv("HOME"),".local","share","Steam")

    vdf_path = os.path.join(steam_path, "steamapps", "libraryfolders.vdf")
    if not os.path.isfile(vdf_path):
        return libraries

    try:
        with open(vdf_path, 'r', encoding='utf-8', errors='ignore') as f:
            contents = f.read()
        # Library entries look like:  "path"   "D:\\SteamLibrary"
        for match in re.finditer(r'"path"\s+"([^"]+)"', contents):
            raw = match.group(1).replace("\\\\", "\\")
            normalized = os.path.normpath(raw)
            if os.path.isdir(normalized) and normalized.lower() not in (p.lower() for p in libraries):
                libraries.append(normalized)
    except Exception as e:
        print(f"Failed to parse libraryfolders.vdf: {e}")

    return libraries


# Modifies the mounts.json file using two provided path parameters
def modify_mounts_json(left_path, right_path):
    # Assuming mounts.json is in the 'data' folder
    json_file = os.path.join(os.getcwd(), 'data', 'mounts.json')

    if not os.path.exists(json_file):
        print(f"Warning: Could not find {json_file}. Skipping JSON modification.")
        return False

    print(f"Updating {json_file}...")
    try:
        # Read the current data
        with open(json_file, 'r') as file:
            data = json.load(file)

        # Target the specific exosuit array
        target_mech = "EXO-49 Emancipator Exosuit"
        if target_mech in data and len(data[target_mech]) >= 2:
            # Update the paths using the function parameters
            data[target_mech][0]["path"] = left_path
            data[target_mech][1]["path"] = right_path

            # Write the updated data back to the file
            with open(json_file, 'w') as file:
                json.dump(data, file, indent=4)

            print(" -> mounts.json updated successfully.")
            return True
        else:
            print(f" -> Error: '{target_mech}' not found in JSON, or array is missing items.")
            return False

    except json.JSONDecodeError as e:
        print(f" -> JSON Formatting Error (Check for trailing commas!): {e}")
        return False
    except Exception as e:
        print(f" -> Error modifying mounts.json: {e}")
        return False

# Auto-detection of the Helldivers 2 bin directory (no manual override).
# Asks Steam directly via libraryfolders.vdf (works regardless of drive/path),
# then falls back to scanning every drive for common Steam library locations.
def auto_detect_helldivers_bin_dir():
    # Preferred: ask Steam where its libraries live.
    for library in get_steam_library_folders():
        candidate = os.path.join(library, "steamapps", "common", "Helldivers 2", "bin")
        if os.path.isdir(candidate):
            return candidate

    # Fallback: brute-force scan every drive letter for common library layouts.
    steam_subpaths = [
        r"Program Files (x86)\Steam\steamapps\common\Helldivers 2\bin",
        r"Program Files\Steam\steamapps\common\Helldivers 2\bin",
        r"SteamLibrary\steamapps\common\Helldivers 2\bin",
        r"Steam\steamapps\common\Helldivers 2\bin",
        r"Games\SteamLibrary\steamapps\common\Helldivers 2\bin",
        r"SteamGames\steamapps\common\Helldivers 2\bin",
        r"steamapps\common\Helldivers 2\bin",
    ]

    for drive_letter in string.ascii_uppercase:
        drive = f"{drive_letter}:\\"
        if os.path.exists(drive):
            for subpath in steam_subpaths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isdir(potential_path):
                    return potential_path

    for drive_letter in string.ascii_lowercase:
        drive = f"{drive_letter}:\\"
        if os.path.exists(drive):
            for subpath in steam_subpaths:
                potential_path = os.path.join(drive, subpath)
                if os.path.isdir(potential_path):
                    return potential_path
    return None


# Public accessor: prefers the user's saved manual override, then auto-detect.
def get_helldivers_bin_dir():
    saved = get_saved_bin_dir()
    if saved:
        return saved
    return auto_detect_helldivers_bin_dir()


# Standard game files that must exist in the Helldivers 2 'bin' folder for
# the modded launch to work. Anti-virus software occasionally deletes these
# (especially msvcp140.dll) after they've been moved into place.
REQUIRED_BIN_FILENAMES = ("discord_game_sdk.dll", "mounts.json", "msvcp140.dll")

# Anchor file that defines the bin folder — used as an additional sanity check.
HELLDIVERS_EXE_FILENAME = "helldivers2.exe"


# Helper for the case where helldivers2.exe is missing from the
# resolved bin folder right before launch. Shows an error explaining the
# situation, asks whether the user wants to manually pick the correct folder,
# and (if they say yes) opens a directory picker. A valid pick is normalized
# and persisted via set_saved_bin_dir so the next CONNECT click uses it.
def prompt_for_new_game_folder(bin_dir, missing_files):
    global _error_count
    _error_count += 1

    files_list = "\n  - ".join(missing_files)
    info_msg = (
        f"helldivers2.exe was not found in the Helldivers 2 'bin' folder:\n"
        f"{bin_dir}\n\n"
        f"Missing file(s):\n  - {files_list}\n\n"
        "The folder currently in use does not look like a valid Helldivers 2 "
        "install. Would you like to select the correct Helldivers 2 folder "
        "now?\n\n"
        "The launcher will reset to its starting state either way; the game "
        "will not be launched on this attempt."
    )
    print(f"[Helldivers 2 Executable Missing] {info_msg}")

    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)

        wants_to_reselect = messagebox.askyesno(
            "Helldivers 2 Executable Missing",
            info_msg,
            parent=root,
            icon='warning',
        )

        if not wants_to_reselect:
            root.destroy()
            return False

        # Suggest the current path (if any) as the dialog's starting location.
        initial_dir = bin_dir if bin_dir and os.path.isdir(bin_dir) else os.path.expanduser("~")
        new_dir = filedialog.askdirectory(
            parent=root,
            title="Select your Helldivers 2 folder (or its 'bin' subfolder)",
            initialdir=initial_dir,
            mustexist=True,
        )

        if not new_dir:
            root.destroy()
            return False

        normalized = normalize_helldivers_bin_dir(new_dir)
        if not normalized:
            messagebox.showerror(
                "Invalid Helldivers 2 Folder",
                f"The selected folder does not look like a valid Helldivers 2 "
                f"install:\n\n{new_dir}\n\n"
                "Please pick either the Helldivers 2 game folder (the one that "
                "contains a 'bin' subfolder) or the 'bin' folder itself.",
                parent=root,
            )
            root.destroy()
            return False

        if not set_saved_bin_dir(normalized):
            messagebox.showerror(
                "Could Not Save Folder",
                "The selected folder is valid, but the launcher failed to "
                "write its config file. Check that the launcher's 'data' "
                "folder is writable.",
                parent=root,
            )
            root.destroy()
            return False

        messagebox.showinfo(
            "Helldivers 2 Folder Saved",
            f"Saved Helldivers 2 folder:\n{normalized}\n\n"
            "The launcher will now reset. Click CONNECT again to launch the "
            "game using the new folder.",
            parent=root,
        )
        root.destroy()
        return True

    except Exception as e:
        print(f"(Could not display folder picker: {e})")
        return False


# Makes sure that helldivers2.exe and all expected
# launcher files exist in the bin folder. Returns the list of missing
# filenames (empty if everything is present). This catches the case where
# anti-virus deletes files after a successful move but before the game is
# actually launched.
def verify_files_in_bin(bin_dir, moved_files):
    expected = {HELLDIVERS_EXE_FILENAME}
    expected.update(REQUIRED_BIN_FILENAMES)
    if moved_files:
        expected.update(moved_files)

    if not bin_dir or not os.path.isdir(bin_dir):
        return sorted(expected)

    return sorted(
        name for name in expected
        if not os.path.isfile(os.path.join(bin_dir, name))
    )


# Files in 'data/' that belong to the launcher itself, not to the game. They
# must not be moved into the game's bin folder during launch process.
LAUNCHER_ONLY_FILENAMES = frozenset({
    "launcher_config.json",
    "exosuit_weapons.json",
})


# Moves files from local 'data' to the game bin, returning a list of moved filenames.
def move_files_to_helldivers():
    source_dir = os.path.join(os.getcwd(), 'data')
    target_dir = get_helldivers_bin_dir()

    if not os.path.exists(source_dir):
        show_error_box(
            "Launcher 'data' Folder Not Found",
            f"The launcher's 'data' folder was not found at:\n{source_dir}\n\n"
            "It may have been deleted by anti-virus software, or the launcher "
            "may have been moved without its 'data' folder."
        )
        return []
    if not target_dir:
        show_error_box(
            "Helldivers 2 Not Found",
            "Could not locate the Helldivers 2 'bin' folder.\n\n"
            "Please make sure Helldivers 2 is installed via Steam. If the game "
            "is on a different drive, open Steam and verify the library is "
            "registered under Steam > Settings > Storage, then try again."
        )
        return []

    # Detect AV-deleted required files BEFORE moving anything.
    required = ["discord_game_sdk.dll", "mounts.json", "msvcp140.dll"]
    missing_from_both = [
        name for name in required
        if not os.path.isfile(os.path.join(source_dir, name))
        and not os.path.isfile(os.path.join(target_dir, name))
    ]
    if missing_from_both:
        show_antivirus_warning(missing_from_both)
        return []

    moved_files = []
    print("Moving files to Helldivers 2...")

    for filename in os.listdir(source_dir):
        source_path = os.path.join(source_dir, filename)
        target_path = os.path.join(target_dir, filename)

        if os.path.isfile(source_path):
            # Skip launcher-internal files — they must stay in 'data/'.
            if filename.lower() in LAUNCHER_ONLY_FILENAMES:
                continue

            # Special conditional logic for dxgi.dll due to reshade
            if filename.lower() == "dxgi.dll":
                if not os.path.exists(target_path):
                    print(f" -> Skipped: {filename} (No existing dxgi.dll found in target directory)")
                    continue

            try:
                if os.path.exists(target_path):
                    os.remove(target_path)
                shutil.move(source_path, target_path)

                # Only track the file for return if it is NOT dxgi.dll
                if filename.lower() != "dxgi.dll":
                    moved_files.append(filename)

                print(f" -> Injected: {filename}")
            except Exception as e:
                show_error_box(
                    "Failed to Move File to Helldivers 2",
                    f"Could not move '{filename}' to:\n{target_dir}\n\n"
                    f"Error: {e}\n\n"
                    "This is usually caused by anti-virus software locking the file. "
                    "Try adding both the launcher folder and the Helldivers 2 'bin' "
                    "folder to your anti-virus exclusions list."
                )
                # Stop on the first failure. The caller is responsible for
                # rolling back any files that were already moved.
                break

    return moved_files


# Ensures required files exist in the local 'data' folder, retrieving any missing ones from the Helldivers 2 bin folder.
def ensure_required_files_in_data():
    required = ["discord_game_sdk.dll", "mounts.json", "msvcp140.dll"]
    data_dir = os.path.join(os.getcwd(), 'data')
    os.makedirs(data_dir, exist_ok=True)

    missing = [f for f in required if not os.path.exists(os.path.join(data_dir, f))]
    if not missing:
        return

    bin_dir = get_helldivers_bin_dir()
    if not bin_dir:
        show_error_box(
            "Helldivers 2 Not Found",
            "Could not locate the Helldivers 2 'bin' folder to recover the "
            "following missing launcher file(s):\n\n  - "
            + "\n  - ".join(missing)
            + "\n\nPlease make sure Helldivers 2 is installed via Steam and "
              "the Steam library containing it is registered under Steam > "
              "Settings > Storage."
        )
        return

    truly_missing = []
    failed_recoveries = []
    for filename in missing:
        source_path = os.path.join(bin_dir, filename)
        target_path = os.path.join(data_dir, filename)
        if os.path.exists(source_path):
            try:
                shutil.move(source_path, target_path)
                print(f" -> Recovered: {filename}")
            except Exception as e:
                print(f" -> Error recovering '{filename}': {e}")
                failed_recoveries.append((filename, str(e)))
        else:
            print(f" -> Missing in bin folder too: {filename}")
            truly_missing.append(filename)

    if truly_missing:
        show_antivirus_warning(truly_missing)

    if failed_recoveries:
        details = "\n".join(f"  - {n}: {err}" for n, err in failed_recoveries)
        show_error_box(
            "Failed to Recover Launcher File(s)",
            "The following file(s) were found in the Helldivers 2 'bin' folder "
            "but could not be moved back into the launcher's 'data' folder:\n\n"
            f"{details}\n\nTry adding both folders to your anti-virus exclusions list."
        )


# Retrieves specific files from the game bin back to the local 'data' folder.
def move_files_back_to_data(files_to_retrieve):
    target_dir = os.path.join(os.getcwd(), 'data')
    source_dir = get_helldivers_bin_dir()

    if not source_dir:
        show_error_box(
            "Helldivers 2 Not Found",
            "Could not locate the Helldivers 2 'bin' folder to retrieve "
            "launcher files from.\n\n"
            "The launcher files may still be inside the game's bin folder. "
            "Please verify Helldivers 2 is installed and the Steam library "
            "containing it is registered in Steam > Settings > Storage."
        )
        return

    print("\nReturning files to local data folder...")
    moved_count = 0
    missing_files = []
    failed_moves = []

    for filename in files_to_retrieve:
        source_path = os.path.join(source_dir, filename)
        target_path = os.path.join(target_dir, filename)

        if os.path.exists(source_path):
            try:
                if os.path.exists(target_path):
                    os.remove(target_path)
                shutil.move(source_path, target_path)
                print(f" -> Retrieved: {filename}")
                moved_count += 1
            except Exception as e:
                print(f" -> Error returning '{filename}': {e}")
                failed_moves.append((filename, str(e)))
        elif not os.path.exists(target_path):
            # File is missing from BOTH the bin folder and the data folder.
            missing_files.append(filename)

    if missing_files:
        show_antivirus_warning(missing_files)

    if failed_moves:
        details = "\n".join(f"  - {n}: {err}" for n, err in failed_moves)
        show_error_box(
            "Failed to Restore File(s) to 'data' Folder",
            "The following file(s) could not be moved back from the Helldivers 2 "
            f"'bin' folder to the launcher's 'data' folder:\n\n{details}\n\n"
            "This is usually caused by anti-virus interference or the launcher being "
            "on a different drive than HD2. Try adding both folders to your anti-virus exclusions list "
            "and ensuring the launcher is on the same drive as HD2."
        )

    print(f"Successfully retrieved {moved_count}/{len(files_to_retrieve)} files.")


# Moves game files, launches the game, and returns files.
# If any step shows an error message box, execution stops immediately and any
# files that were already moved into the game's bin folder are restored.
def launch_and_restore():
    print("Starting CGW")

    errors_before_inject = error_count_since_reset()

    # "Inject" files. move_files_to_helldivers handles its own error
    # popups (missing data folder, missing bin folder, AV-deleted required
    # files, per-file move failures) and stops at the first failure.
    moved_files = move_files_to_helldivers()

    if error_count_since_reset() > errors_before_inject:
        # An error box was shown. Roll back anything that did get moved and
        # do not proceed to launch the game.
        if moved_files:
            print("Errors during injection. Restoring files to 'data'...")
            move_files_back_to_data(moved_files)
        return

    data_dir = os.path.join(os.getcwd(), 'data')
    has_dxgi_override = any(
        f.lower() == "dxgi.dll" and os.path.isfile(os.path.join(data_dir, f))
        for f in os.listdir(data_dir)
    ) if os.path.isdir(data_dir) else False
    if not moved_files and not has_dxgi_override:
        print("No files were moved. Aborting sequence.")
        return

    game_dir = get_helldivers_bin_dir()
    if not game_dir or not os.path.isdir(game_dir):
        show_error_box(
            "Helldivers 2 Folder Not Found",
            "The Helldivers 2 'bin' folder could not be resolved at launch time."
            + (f"\n\nExpected at:\n{game_dir}" if game_dir else "")
            + "\n\nThe launcher will restore its files and stop. Try clicking "
              "SET GAME FOLDER and re-selecting your Helldivers 2 install."
        )
        move_files_back_to_data(moved_files)
        return

    print("\nLaunching helldivers2.exe...")

    steam_path = find_steam_exe()
    if not steam_path:
        show_error_box(
            "Steam Not Found",
            "Could not locate steam.exe. Please make sure Steam is installed.\n\n"
            "The launcher will restore its files and stop."
        )
        move_files_back_to_data(moved_files)
        return

    # Right before handing off to Steam, verify
    # that helldivers2.exe AND every required launcher file is actually
    # present in the bin folder.
    missing_in_bin = verify_files_in_bin(game_dir, moved_files)
    if missing_in_bin:
        if HELLDIVERS_EXE_FILENAME in missing_in_bin:
            # helldivers2.exe isn't where we expect it — most likely the
            # user picked the wrong folder. Give them a chance to re-select.
            prompt_for_new_game_folder(game_dir, missing_in_bin)
            move_files_back_to_data(moved_files)
            return

        # helldivers2.exe is present, but one or more launcher files are
        # missing — almost always an anti-virus deletion.
        files_list = "\n  - ".join(missing_in_bin)
        show_error_box(
            "Required Files Missing From Helldivers 2 'bin' Folder",
            "The launcher was about to start Helldivers 2, but the following "
            f"file(s) are missing from:\n{game_dir}\n\n"
            f"  - {files_list}\n\n"
            "They were most likely deleted by your anti-virus software after "
            "the launcher moved them into place.\n\n"
            "Please check your anti-virus quarantine, restore the file(s), "
            "and add BOTH the launcher folder AND the Helldivers 2 'bin' "
            "folder to your anti-virus exclusions list before trying again.\n\n"
            "The launcher will restore whatever it can and stop without "
            "launching the game."
        )
        move_files_back_to_data(moved_files)
        return

    game_app_id = "553850"
    try:
        subprocess.Popen([steam_path, "-applaunch", game_app_id], cwd=game_dir)
    except Exception as e:
        show_error_box(
            "Failed to Launch Helldivers 2",
            f"Could not start the game via Steam.\n\nError: {e}\n\n"
            "The launcher will restore its files and stop."
        )
        move_files_back_to_data(moved_files)
        return

    print("Waiting 45 seconds for game initialization...")
    time.sleep(45)

    move_files_back_to_data(moved_files)
    print("Successfully launched game and moved files back.")