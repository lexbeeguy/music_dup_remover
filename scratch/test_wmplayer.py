import os
import time
import win32com.client

filepath = os.path.abspath("test_music/01 Mother And Child Reunion.m4a")
print("Target file:", filepath)

try:
    player = win32com.client.Dispatch("WMPlayer.OCX")
    player.settings.autoStart = True
    player.settings.volume = 80
    player.URL = filepath
    print("WMPlayer URL set successfully.")
    
    time.sleep(3)
    player.controls.stop()
    print("WMPlayer playback test passed!")
except Exception as e:
    print("WMPlayer error:", e)
