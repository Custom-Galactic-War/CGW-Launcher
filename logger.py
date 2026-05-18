import atexit
import faulthandler
import getpass
import logging
import logging.handlers
import os
import platform
import sys
import tempfile
import threading
import traceback
from datetime import datetime
from typing import Optional

import constants

_LOG_FILE_NAME = "launcher.log"
_FAULT_FILE_NAME = "faulthandler.log"
_LOG_DIR_REL = os.path.join("data", "logs")
_LOG_MAX_BYTES = 1 * 1024 * 1024  # 1 MB
_LOG_BACKUP_COUNT = 5

_setup_lock = threading.RLock()
_log_dir_resolved: Optional[str] = None
_log_file_resolved: Optional[str] = None
_faulthandler_file = None  # kept open for the life of the process


def _redact_username(s: str) -> str:
    # Replace the current Windows username with <user> in arbitrary strings.
    try:
        user = getpass.getuser()
    except Exception:
        return s
    if not user:
        return s
    return s.replace(user, "<user>")


def _try_probe_write(directory: str) -> bool:
    """Return True iff `directory` is usable for our log file.

    Two checks, because on Windows the directory may be writable (NTFS ACL)
    while a pre-existing `launcher.log` file is read-only (file attribute).
    RotatingFileHandler would then crash trying to open the existing file
    for append.

    1. Create+delete a temp file in `directory` (tests directory ACL).
    2. If `launcher.log` already exists, open it for append (tests file ACL)."""
    try:
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            dir=directory, prefix=".probe-", delete=True
        ):
            pass
    except OSError:
        return False

    existing = os.path.join(directory, _LOG_FILE_NAME)
    if os.path.exists(existing):
        try:
            with open(existing, "a", encoding="utf-8"):
                pass
        except OSError:
            return False
    return True


def _resolve_log_dir() -> str:
    """Pick a writable log directory.
    1. <cwd>/data/logs/  (next to the exe; same place launcher_config.json lives)
    2. %LOCALAPPDATA%\\E-710 Launcher\\logs  (if 1 isn't writable)
    3. <tempdir>/E-710 Launcher logs  (last resort — always writable)

    Best-effort: returns a path on every realistic system. Can raise
    OSError only if even %TEMP% is unwritable (truly broken host) — that
    propagates to setup_logging and is caught by the run.py:__main__
    breadcrumb wrapper."""
    primary = os.path.join(os.getcwd(), _LOG_DIR_REL)
    if _try_probe_write(primary):
        return primary

    fallback_root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    fallback = os.path.join(fallback_root, "E-710 Launcher", "logs")
    if _try_probe_write(fallback):
        return fallback

    last_resort = os.path.join(tempfile.gettempdir(), "E-710 Launcher logs")
    os.makedirs(last_resort, exist_ok=True)
    return last_resort


def get_log_file_path() -> Optional[str]:
    """Return the active log file path, or None if setup hasn't run / failed.
    Callers (e.g. dialog footer, UI button) must handle the None case."""
    return _log_file_resolved


def get_log_dir() -> Optional[str]:
    return _log_dir_resolved


def is_initialized() -> bool:
    return _log_file_resolved is not None


def _format_preamble() -> str:
    return (
        "=" * 72 + "\n"
        f"E-710 Launcher session start: {datetime.now().isoformat(timespec='seconds')}\n"
        f"  Version       : {getattr(constants, 'LAUNCHER_VERSION', 'unknown')}\n"
        f"  Python        : {sys.version.splitlines()[0]}\n"
        f"  Platform      : {platform.platform()}\n"
        f"  Frozen (exe)  : {getattr(sys, 'frozen', False)}\n"
        f"  CWD           : {_redact_username(os.getcwd())}\n"
        f"  argv          : {_redact_username(repr(sys.argv))}\n"
        + "=" * 72
    )


class _UsernameRedactionFilter(logging.Filter):
    """Apply _redact_username to every formatted log record. Catches the
    case where an OSError/PermissionError exception message embeds a
    home-directory path (e.g. C:\\Users\\<actual-username>\\...) that the
    plain preamble redactor cannot reach. Operates on the post-format
    string so it covers exception tracebacks too."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            user = getpass.getuser()
        except Exception:
            return True
        if not user:
            return True
        if isinstance(record.msg, str) and user in record.msg:
            record.msg = record.msg.replace(user, "<user>")
        if record.args:
            record.args = tuple(
                a.replace(user, "<user>") if isinstance(a, str) and user in a else a
                for a in (record.args if isinstance(record.args, tuple) else (record.args,))
            )
        if record.exc_info:
            # Materialize the traceback now so we can redact it; otherwise
            # the formatter would expand it after this filter has run.
            if record.exc_text is None:
                record.exc_text = logging.Formatter().formatException(record.exc_info)
            record.exc_text = record.exc_text.replace(user, "<user>")
            record.exc_info = None  # already materialized into exc_text
        return True


def _safe_isatty(stream) -> bool:
    """isatty() can raise on wrapped/dead streams under PyInstaller --windowed."""
    if stream is None:
        return False
    try:
        return stream.isatty()
    except (OSError, ValueError):
        return False


def _close_faulthandler_file():
    """Registered with atexit. Closes the persistent faulthandler file so the
    last buffer is flushed and we don't leak a file descriptor across
    re-entrant setup paths."""
    global _faulthandler_file
    if _faulthandler_file is not None:
        try:
            faulthandler.disable()
        except Exception:
            pass
        try:
            _faulthandler_file.close()
        except OSError:
            pass
        _faulthandler_file = None


def setup_logging() -> Optional[str]:
    """Configure root logger, install hooks, open faulthandler.
    Idempotent and thread-safe — safe to call more than once.
    Returns the resolved log file path, or None on catastrophic failure."""
    global _log_dir_resolved, _log_file_resolved, _faulthandler_file

    with _setup_lock:
        if _log_file_resolved is not None:
            return _log_file_resolved

        _log_dir_resolved = _resolve_log_dir()
        _log_file_resolved = os.path.join(_log_dir_resolved, _LOG_FILE_NAME)

        root = logging.getLogger()
        root.setLevel(logging.DEBUG)
        # Wipe any handlers a library may have attached (pypresence is known to).
        root.handlers.clear()

        fmt = logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s [%(threadName)s] %(name)s: %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        file_handler = logging.handlers.RotatingFileHandler(
            _log_file_resolved,
            maxBytes=_LOG_MAX_BYTES,
            backupCount=_LOG_BACKUP_COUNT,
            encoding="utf-8",
            delay=False,
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(fmt)
        file_handler.addFilter(_UsernameRedactionFilter())
        root.addHandler(file_handler)

        if _safe_isatty(sys.stdout):
            stream_handler = logging.StreamHandler(sys.stdout)
            stream_handler.setLevel(logging.INFO)
            stream_handler.setFormatter(fmt)
            root.addHandler(stream_handler)

        logging.getLogger("e710").info("\n%s", _format_preamble())

        # Python-level uncaught exceptions (main thread).
        def _excepthook(exc_type, exc, tb):
            if issubclass(exc_type, KeyboardInterrupt):
                sys.__excepthook__(exc_type, exc, tb)
                return
            logging.getLogger("uncaught").critical(
                "Uncaught exception:\n%s",
                "".join(traceback.format_exception(exc_type, exc, tb)),
            )

        sys.excepthook = _excepthook

        # Worker-thread uncaught exceptions. QThread.run runs in a Python
        # thread, so this fires for InjectionThread / DiscordRPCManager
        # bodies that don't already catch. Requires Python 3.8+.
        def _thread_excepthook(args):
            if issubclass(args.exc_type, SystemExit):
                return
            thread_name = args.thread.name if args.thread else "<unknown>"
            logging.getLogger("thread").critical(
                "Uncaught exception in thread %r:\n%s",
                thread_name,
                "".join(
                    traceback.format_exception(
                        args.exc_type, args.exc_value, args.exc_traceback
                    )
                ),
            )

        threading.excepthook = _thread_excepthook

        # Native crashes (segfault in PyQt6, discord_game_sdk.dll, pypresence).
        # Separate file so faulthandler can write even when the logging
        # subsystem is wedged. atexit closes the FD on clean shutdown so
        # a future re-entrant setup_logging would not leak it.
        if _faulthandler_file is None:
            fault_path = os.path.join(_log_dir_resolved, _FAULT_FILE_NAME)
            try:
                _faulthandler_file = open(
                    fault_path, "a", encoding="utf-8", buffering=1
                )
                _faulthandler_file.write(
                    f"\n--- faulthandler armed at "
                    f"{datetime.now().isoformat(timespec='seconds')} ---\n"
                )
                faulthandler.enable(file=_faulthandler_file, all_threads=True)
                atexit.register(_close_faulthandler_file)
            except OSError:
                logging.getLogger("e710").warning(
                    "Could not open faulthandler file at %s", fault_path
                )

        return _log_file_resolved
