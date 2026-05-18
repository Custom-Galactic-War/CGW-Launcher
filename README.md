msvcp140.dll is not in helldivers's bin. It's in the compatdata folder .../system32 so you need to copy that.

after cloning, set up with...
```
python -m venv ~/.python/CGW-Launcher-Linux
source ~/.python/CGW-Launcher-Linux/bin/activate
pip install -r requirements.txt
```
then
`python ./run.py`
