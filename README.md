msvcp140.dll is not in helldivers's bin. It's in the compatdata folder .../system32 so you need to copy that.

after cloning, set up with...
```
python -m venv ~/.python/CGW-Launcher-Linux
source ~/.python/CGW-Launcher-Linux/bin/activate
pip install -r requirements.txt
```
then
`python ./run.py`

Unable to authenticate via discord so the CGW is unavailable as yet.

Possible solution at https://github.com/ValveSoftware/Proton/wiki/Enabling-Discord-Rich-Presence ?
