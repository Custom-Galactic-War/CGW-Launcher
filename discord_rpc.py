import threading
import time
from pypresence import Presence
from PyQt6.QtCore import QThread


class DiscordRPCManager(QThread):
    """Background Discord Rich Presence connection.

    Holds a single pypresence pipe and exposes thread-safe set_lobby /
    clear_lobby methods that can be called from the Qt main thread. The
    "current" presence payload is cached so that:
      - calling set_lobby before the IPC is connected just queues the update
        (it's applied as soon as run() finishes connecting), and
      - if pypresence reconnects internally, the most recent intent survives.
    """

    def __init__(self, client_id):
        super().__init__()
        self.client_id = client_id
        self.rpc = None
        self.is_running = True
        # Lock guards `self.rpc` (the pypresence handle) AND any pipe write,
        # since pypresence sends raw bytes over a single non-thread-safe pipe.
        self._lock = threading.Lock()
        # The current intent. Defaults to idle; replaced by set_lobby /
        # clear_lobby. Applied to the pipe as soon as it's available.
        self._pending_presence = self._idle_presence()

    # ---- presence payload builders --------------------------------------

    @staticmethod
    def _idle_presence():
        return {"state": "In the Launcher"}

    @staticmethod
    def _lobby_presence(lobby_tail, redirect_base):
        payload = {
            "state": "Hosting Lobby",
            "details": "Custom Galactic War",
            # party_id makes Discord render "1 of 4" on the presence card and
            # is the anchor that "Ask to Join" would key off if we ever enable
            # that flow. Tying it to the lobby id keeps it stable per lobby.
            "party_id": f"cgw-{lobby_tail}",
            "party_size": [1, 4],
        }
        base = (redirect_base or "").strip()
        if base:
            url = f"{base.rstrip('/')}/?id={lobby_tail}"
            payload["buttons"] = [{"label": "Join Lobby", "url": url}]
        return payload

    # ---- internal: apply a payload to the live pipe ---------------------

    def _apply_presence_locked(self, payload):
        """Send `payload` over the pipe. Caller must hold self._lock and have
        already verified self.rpc is not None. The persistent large image is
        merged in here so callers don't have to repeat it."""
        merged = {
            "large_image": "icon",
            "large_text": "E-710 Launcher",
        }
        merged.update(payload)
        try:
            self.rpc.update(**merged)
        except Exception as e:
            print(f"[RPC] update failed: {e}")

    # ---- public API (callable from any thread) --------------------------

    def set_lobby(self, lobby_tail, redirect_base):
        """Switch Discord presence to 'Hosting Lobby' with a Join Lobby button.

        `lobby_tail` is the "<lobby_id>/<host_steam_id>" portion of the Steam
        join URL (as returned by functions.parse_lobby_url). `redirect_base`
        is the https:// page that redirects to steam:// — if empty/None the
        button is omitted but the party-size indicator still appears."""
        with self._lock:
            self._pending_presence = self._lobby_presence(lobby_tail, redirect_base)
            if self.rpc:
                self._apply_presence_locked(self._pending_presence)

    def clear_lobby(self):
        """Reset Discord presence to the default 'In the Launcher' state."""
        with self._lock:
            self._pending_presence = self._idle_presence()
            if self.rpc:
                self._apply_presence_locked(self._pending_presence)

    # ---- thread body ----------------------------------------------------

    def run(self):
        try:
            rpc = Presence(self.client_id)
            rpc.connect()
            with self._lock:
                self.rpc = rpc
                # Replay whatever the most recent intent is — usually the
                # default idle payload, but set_lobby may have run before
                # we finished connecting.
                self._apply_presence_locked(self._pending_presence)
            # Idle loop. Discord doesn't require periodic refreshes; we just
            # need to keep the connection open and respond promptly to stop().
            while self.is_running:
                for _ in range(15):
                    if not self.is_running:
                        break
                    time.sleep(1)
        except Exception as e:
            print(f"[RPC] Discord connection failed: {e}")

    def stop(self):
        self.is_running = False
        with self._lock:
            if self.rpc:
                # clear() removes the activity from Discord's UI; close() alone
                # only tears down the IPC pipe and Discord will keep showing
                # the last-pushed presence until something explicitly clears
                # it.
                try:
                    self.rpc.clear()
                except Exception:
                    pass
                try:
                    self.rpc.close()
                except Exception:
                    pass
                self.rpc = None
