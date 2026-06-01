import os
import platform
import re
import shutil
import string
import subprocess
import threading
import time
import json
import tkinter as tk
from tkinter import messagebox

try:
    import winreg
except ImportError:
    winreg = None

import constants

# The thread the interpreter started on. tkinter (and any GUI toolkit) may only
# be touched from this thread; doing so from a worker thread causes a hard
# native crash ("Tcl_AsyncDelete: async handler deleted by the wrong thread"),
# which is exactly what silently closed the launcher for some users.
_MAIN_THREAD = threading.main_thread()

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


# Error machinery. Errors can be raised from either the GUI/main thread
# (startup, close) or the InjectionThread worker (during launch). To stay
# crash-free:
#   * The error COUNT (used by the UI to decide success/failure) is always
#     updated synchronously under a lock.
#   * The actual DIALOG is only ever shown on the main thread. Main-thread
#     errors display immediately; worker-thread errors are queued and the main
#     thread drains them via drain_pending_errors() once the worker finishes.
_error_lock = threading.RLock()
_error_count = 0
_pending_errors = []          # (title, message) queued from worker threads
_main_thread_display = None   # callable(title, message); set by the GUI layer


def set_main_thread_display(fn):
    """Register a callback the main thread uses to show an error dialog. The
    callback MUST only be invoked on the main thread (this module guarantees
    that). Passing None reverts to the tkinter fallback."""
    global _main_thread_display
    _main_thread_display = fn


def reset_error_count():
    global _error_count
    with _error_lock:
        _error_count = 0
        _pending_errors.clear()


def error_count_since_reset():
    with _error_lock:
        return _error_count


def drain_pending_errors():
    """Return and clear the list of errors queued from worker threads. Call
    this from the main thread (e.g. when the injection thread finishes) to
    display them safely."""
    with _error_lock:
        errors = list(_pending_errors)
        _pending_errors.clear()
    return errors


def _display_on_main_thread(title, message):
    """Actually show the dialog. MUST be called on the main thread only."""
    if _main_thread_display is not None:
        try:
            _main_thread_display(title, message)
            return
        except Exception as e:
            print(f"(GUI error display failed, falling back to tkinter: {e})")
    # Fallback for headless/standalone use (no GUI layer registered). tkinter
    # is only safe here because this function is main-thread-only.
    try:
        root = tk.Tk()
        root.withdraw()
        root.attributes('-topmost', True)
        messagebox.showerror(title, message, parent=root)
        root.destroy()
    except Exception as e:
        print(f"(Could not display message box: {e})")


# Record an error and surface it to the user. Every call increments the error
# counter so the launcher knows an error occurred. The dialog is shown
# immediately when called on the main thread, or queued for the main thread to
# display when called from a worker thread (NEVER touches tkinter off-thread).
def show_error_box(title, message):
    global _error_count
    print(f"[{title}] {message}")
    with _error_lock:
        _error_count += 1
        on_main = threading.current_thread() is _MAIN_THREAD
        if not on_main:
            # Defer to the main thread — touching the GUI here would crash.
            _pending_errors.append((title, message))
    if on_main:
        _display_on_main_thread(title, message)


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
    "~/snap/steam/common/.local/share/Steam",  # Snap install
)


# Candidate paths to the Steam launcher binary on Linux, checked in order when
# `steam` isn't found on PATH. Covers apt/dnf/pacman, Snap (/snap/bin/steam),
# user-local installs, and the legacy ~/.steam/steam.sh launcher.
_LINUX_STEAM_BINARIES = (
    "/usr/bin/steam",
    "/usr/games/steam",
    "/usr/local/bin/steam",
    "/snap/bin/steam",
    os.path.expanduser("~/.local/bin/steam"),
    os.path.expanduser("~/.steam/steam.sh"),
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

    # Native Linux Steam — prefer whatever's on PATH (covers apt/dnf/pacman and
    # Snap, since /snap/bin is normally on PATH).
    found = shutil.which("steam")
    if found:
        return [found]

    for p in _LINUX_STEAM_BINARIES:
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
    for path in _LINUX_STEAM_BINARIES:
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


# Enumerate running process executable names on Windows via the Win32 Toolhelp
# API (CreateToolhelp32Snapshot). Returns a set of lowercase names, or None if
# the API call fails. This is used in preference to `tasklist` because a
# --windowed (no-console) PyInstaller build can get None back from tasklist's
# captured stdout, which previously crashed the launch with
# "'NoneType' object has no attribute 'lower'".
def _list_windows_process_names():
    try:
        import ctypes
        from ctypes import wintypes
    except Exception:
        return None

    TH32CS_SNAPPROCESS = 0x00000002
    MAX_PATH = 260
    INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * MAX_PATH),
        ]

    try:
        k = ctypes.windll.kernel32
        # Pin the prototypes so handles aren't truncated to 32 bits on x64.
        k.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k.Process32First.restype = wintypes.BOOL
        k.Process32First.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
        k.Process32Next.restype = wintypes.BOOL
        k.Process32Next.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32)]
        k.CloseHandle.restype = wintypes.BOOL
        k.CloseHandle.argtypes = [wintypes.HANDLE]

        snapshot = k.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        if not snapshot or snapshot == INVALID_HANDLE_VALUE:
            return None
    except Exception:
        return None

    names = set()
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if not k.Process32First(snapshot, ctypes.byref(entry)):
            return names
        while True:
            try:
                names.add(entry.szExeFile.decode("ascii", "ignore").lower())
            except Exception:
                pass
            if not k.Process32Next(snapshot, ctypes.byref(entry)):
                break
    except Exception:
        return None
    finally:
        try:
            k.CloseHandle(snapshot)
        except Exception:
            pass
    return names


# Returns True if a helldivers2.exe process is currently running. Used to
# block CONNECT clicks while the game is already open — moving files into the
# bin folder while the game has them mapped is a recipe for corrupted state.
# The helldivers2.exe name is the same on Linux Proton (Wine runs it under the
# same process name), so the same check works on both platforms.
def is_helldivers_running():
    target = HELLDIVERS_EXE_FILENAME.lower()

    if _IS_WINDOWS:
        # Primary: enumerate processes directly via the Win32 API — reliable
        # even in a frozen --windowed build.
        names = _list_windows_process_names()
        if names is not None:
            return target in names

        # Fallback: tasklist. Guard stdout because in some windowed/frozen
        # environments the captured stdout comes back as None (the original
        # cause of the crash).
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
        output = (result.stdout or "") + (result.stderr or "")
        return target in output.lower()

    # Linux: scan /proc for any process matching helldivers2.exe. Under Proton
    # the game runs inside Wine, so we check two things per process:
    #   * /proc/<pid>/comm    — the process name, but truncated to 15 chars
    #     ("helldivers2.exe" is exactly 15, so it fits; older kernels may clip).
    #   * /proc/<pid>/cmdline — the full argv (NUL-separated). Wine/Proton
    #     launches the game by full path, so "helldivers2.exe" appears here even
    #     when comm is something generic. This is the reliable signal.
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
        proc_dir = os.path.join(proc_root, entry)

        # comm — fast path, prefix match to tolerate 15-char truncation.
        try:
            with open(os.path.join(proc_dir, "comm"), "r",
                      encoding="utf-8", errors="ignore") as f:
                comm = f.read().strip().lower()
            if comm and (comm == target or target.startswith(comm)):
                return True
        except (OSError, IOError):
            pass

        # cmdline — full argv; catches the Proton ".../helldivers2.exe" case.
        try:
            with open(os.path.join(proc_dir, "cmdline"), "rb") as f:
                cmdline = f.read().replace(b"\x00", b" ").decode(
                    "utf-8", "ignore").lower()
            if target in cmdline:
                return True
        except (OSError, IOError):
            pass
    return False


# How long (seconds) to wait for the helldivers2.exe process to appear after
# asking Steam to launch it. Generous enough to cover Steam cold-start, a small
# pending update, and anti-cheat/shader init. If the process never appears
# within this window the launch is treated as failed.
GAME_LAUNCH_TIMEOUT_SECONDS = 120

# Grace period (seconds) after the game process appears before moving the
# injected files back out of 'bin'. The DLLs are loaded at process start, so a
# short wait is enough to also cover any remaining file reads during init.
POST_LAUNCH_GRACE_SECONDS = 20


# Polls until a helldivers2.exe process is detected or the timeout elapses.
# Returns True if the game started, False if it never appeared in time.
def wait_for_helldivers_to_start(timeout_seconds=GAME_LAUNCH_TIMEOUT_SECONDS,
                                 poll_interval=2.0):
    deadline = time.monotonic() + timeout_seconds
    while True:
        if is_helldivers_running():
            return True
        if time.monotonic() >= deadline:
            return False
        time.sleep(poll_interval)


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
            "This is usually caused by anti-virus interference or insufficient permissions. Try adding "
            "both folders to your anti-virus exclusions list. This will not effect "
            "this run of CGW, but if the files are not moved back when you close the launcher "
            "then the next time you try to play vanilla GW you will play CGW instead. To fix this "
            "just reopen then close the launcher, or manually remove the msvcp140.dll from the bin folder."
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

    # 6. Confirm the game actually started. Popen succeeding only means Steam
    #    was spawned — NOT that the game launched (Steam could be logged out,
    #    offline, mid-update, or the game not owned). Poll for the process so a
    #    silent non-launch becomes a clear error instead of a no-op.
    print("Waiting for Helldivers 2 to start...")
    if not wait_for_helldivers_to_start():
        show_error_box(
            "Helldivers 2 Did Not Start",
            "The launcher asked Steam to start Helldivers 2, but the game did "
            f"not start within {GAME_LAUNCH_TIMEOUT_SECONDS} seconds.\n\n"
            "Common causes:\n"
            "  - Steam is logged out, offline, or downloading an update.\n"
            "  - Helldivers 2 is not owned on the signed-in Steam account.\n"
            "  - A Steam pop-up is waiting for your input.\n\n"
            "Your launcher files have been restored. Make sure Steam is "
            "running and signed in, then click CONNECT again."
        )
        move_files_back_to_files(moved_files)
        return

    # 7. The process exists, so its injected DLLs are already loaded. Give the
    #    game a short grace period to finish reading any remaining injected
    #    files, then move them back out so 'bin' is left clean.
    print(f"Helldivers 2 started. Restoring files in {POST_LAUNCH_GRACE_SECONDS}s...")
    time.sleep(POST_LAUNCH_GRACE_SECONDS)

    move_files_back_to_files(moved_files)
    print("Successfully launched game and moved files back.")
