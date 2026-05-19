### Setup:

```
git clone --recurse-submodules https://github.com/shawarden/CGW-Launcher-Linux.git
cd CGW-Launcher-Linux
python -m venv ~/.python/CGW-Launcher-Linux
source ~/.python/CGW-Launcher-Linux/bin/activate
pip install -r requirements.txt
```

You will need to download the updated [mscvp140.dll](https://cdn.discordapp.com/attachments/1506103892465680444/1506123948847403199/msvcp140.dll?ex=6a0d1ebb&is=6a0bcd3b&hm=eaba295dbe4905c9fb44b310a7bf5a14ed684b2636b345c00468820a148e41ed&) and [discord_game_sdk.dll](https://cdn.discordapp.com/attachments/1506103892465680444/1506105182243520662/discord_game_sdk.dll?ex=6a0d0d41&is=6a0bbbc1&hm=5b2111c233473310851004433084ccfee3a280e7e61275e42768b1df9f7d8cb5&) from the Discord's [linux-testing](https://discord.gg/vf9JRNdjyq) lobby and place them in the `.../CGW-Launcher-Linux/data` directory.

You also need the [wine-discord-ipc-bridge.exe](https://github.com/0e4ef622/wine-discord-ipc-bridge/releases/download/v0.0.3/winediscordipcbridge.exe) binary to be in the `wine-discord-ipc-bridge` submodule directory and as per the [wine-discord-ipc-bridge](https://github.com/0e4ef622/wine-discord-ipc-bridge) instructions put `/path/to/CGW-Launcher-Linux/wine-discord-ipc-bridge/winediscordipcbridge-steam.sh %command%` in the game's launch options.

Avoid spaces in the path because not even single quoting paths seems to be respected.

---

### Launch:

```
cd /path/to/CGW-Launcher-Linux
source ~/.python/CGW-Launcher-Linux/bin/activate
python run.py
```
