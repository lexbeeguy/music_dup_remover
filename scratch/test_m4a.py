import ctypes
import time
import os

filepath = os.path.abspath("test_music/01 Mother And Child Reunion.m4a")
print("Target file:", filepath, "Exists:", os.path.exists(filepath))

mci = ctypes.windll.winmm.mciSendStringW

# Close any open alias
mci("close preview", None, 0, 0)

# Open M4A
cmd_open = f'open "{filepath}" alias preview'
res_open = mci(cmd_open, None, 0, 0)
print("MCI Open result:", res_open)

if res_open == 0:
    res_play = mci("play preview", None, 0, 0)
    print("MCI Play result:", res_play)
    time.sleep(2)
    mci("close preview", None, 0, 0)
else:
    # Get error string
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.winmm.mciGetErrorStringW(res_open, buf, 256)
    print("MCI Error:", buf.value)
