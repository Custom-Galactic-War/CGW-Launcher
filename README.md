msvcp140.dll is not in helldivers's bin. It's in the compatdata folder .../system32 so you need to copy that.

after cloning, set up with...
```
python -m venv ~/.python/CGW-Launcher-Linux
source ~/.python/CGW-Launcher-Linux/bin/activate
pip install -r requirements.txt
```
then
`python ./run.py`

Access to CGW is unavailable as it's unable to authenticate via discord. Possible solutions:

https://github.com/ValveSoftware/Proton/wiki/Enabling-Discord-Rich-Presence last updated ~2023

https://docs.discord.com/developers/developer-tools/game-sdk officially from discord?


