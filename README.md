After cloning, set up with...
```
python -m venv ~/.python/CGW-Launcher-Linux
source ~/.python/CGW-Launcher-Linux/bin/activate
pip install -r requirements.txt
```
then
`python ./run.py`

---

Github doesn't include the mscvp140.dll. You need to download the windows installer from the discord and copy the data folder

---

Access to CGW is unavailable as it's unable to authenticate via discord. Possible solutions:

https://github.com/ValveSoftware/Proton/wiki/Enabling-Discord-Rich-Presence last updated ~2023

https://docs.discord.com/developers/developer-tools/game-sdk officially from discord?

---

When launching there is an error "[There is no Windows program configured to open this type of file](https://i.imgur.com/dzpsQGe.png)." followed by "[Failed to retrieve Discord ID](https://i.imgur.com/Jp1oevh.png)" and of course it doesn't access CGW. Game then crashes with "[GameGuard: Hack attempt Detected! ... Error code: 1013](https://i.imgur.com/KJUZzpT.png)" because of the injection.

---
