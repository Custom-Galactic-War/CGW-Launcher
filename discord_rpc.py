import time
from pypresence import Presence
from PyQt6.QtCore import QThread

class DiscordRPCManager(QThread):
    def __init__(self, client_id):
        super().__init__()
        self.client_id = client_id
        self.rpc = None
        
        self.is_running = True

    def run(self):
        try:
            self.rpc = Presence(self.client_id)
            self.rpc.connect()            
            self.rpc.update(
                state="In the Launcher",
                large_image="icon", 
                large_text="E-710 Launcher"
            )
            while self.is_running:
                for _ in range(15):
                    if not self.is_running:
                        break
                    time.sleep(1)
                    
        except Exception as e:
            print(f"[RPC] Discord connection failed: {e}")

    def stop(self):
        self.is_running = False
        if self.rpc:
            try:
                self.rpc.close()
            except Exception:
                pass