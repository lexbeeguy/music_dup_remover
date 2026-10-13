import os
import sys
import logging
from typing import Optional, Callable

# Suppress pygame banner
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Audio preview player: pygame for MP3/WAV/FLAC/OGG, plus Windows Media Player (COM) for M4A/AAC/WMA on Windows."""

    def __init__(self, status_callback: Optional[Callable[[str, bool], None]] = None):
        self.current_filepath: Optional[str] = None
        self.is_paused = False
        self.status_callback = status_callback
        self.backend = "pygame"  # "pygame" or "wmplayer"
        self.wmplayer = None

        # 1. Initialize pygame mixer
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
        except Exception as e:
            logger.warning(f"Pygame mixer init notice: {e}")

        # 2. Initialize Windows Media Player COM object on Windows
        if sys.platform == "win32":
            try:
                import win32com.client
                self.wmplayer = win32com.client.Dispatch("WMPlayer.OCX")
            except Exception as e:
                logger.warning(f"WMPlayer COM init notice: {e}")

    def load_and_play(self, filepath: str) -> bool:
        """Load and play the given audio file (supports .m4a, .mp3, .wav, .flac, .aac, .ogg)."""
        if not os.path.exists(filepath):
            if self.status_callback:
                self.status_callback("File Not Found", False)
            return False

        ext = os.path.splitext(filepath)[1].lower()
        self.stop()
        self.current_filepath = filepath
        self.is_paused = False

        # Direct M4A/AAC/MP4 files to Windows Media Player engine
        use_wmplayer = (ext in [".m4a", ".aac", ".mp4", ".wma"]) or (not pygame.mixer.get_init())

        if use_wmplayer and self.wmplayer:
            try:
                self.backend = "wmplayer"
                self.wmplayer.URL = os.path.abspath(filepath)
                self.wmplayer.controls.play()
                if self.status_callback:
                    self.status_callback(os.path.basename(filepath), True)
                return True
            except Exception as e:
                logger.error(f"WMPlayer error loading {filepath}: {e}")

        # Try Pygame for MP3, WAV, FLAC, OGG
        try:
            self.backend = "pygame"
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            if self.status_callback:
                self.status_callback(os.path.basename(filepath), True)
            return True
        except Exception as e:
            logger.warning(f"Pygame playback error for {filepath}: {e}")
            # Fallback to WMPlayer if Pygame fails
            if self.wmplayer:
                try:
                    self.backend = "wmplayer"
                    self.wmplayer.URL = os.path.abspath(filepath)
                    self.wmplayer.controls.play()
                    if self.status_callback:
                        self.status_callback(os.path.basename(filepath), True)
                    return True
                except Exception as ex:
                    logger.error(f"WMPlayer fallback error: {ex}")

        if self.status_callback:
            self.status_callback(f"Playback Error: {os.path.basename(filepath)}", False)
        return False

    def toggle_play_pause(self) -> bool:
        """Toggle between play and pause."""
        if not self.current_filepath:
            return False

        if self.backend == "wmplayer" and self.wmplayer:
            try:
                if self.is_paused:
                    self.wmplayer.controls.play()
                    self.is_paused = False
                else:
                    self.wmplayer.controls.pause()
                    self.is_paused = True
                if self.status_callback:
                    self.status_callback(os.path.basename(self.current_filepath), not self.is_paused)
                return True
            except Exception as e:
                logger.error(f"WMPlayer play/pause error: {e}")

        if self.backend == "pygame":
            if self.is_paused:
                pygame.mixer.music.unpause()
                self.is_paused = False
            else:
                pygame.mixer.music.pause()
                self.is_paused = True
            if self.status_callback:
                self.status_callback(os.path.basename(self.current_filepath), not self.is_paused)
            return True

        return False

    def stop(self):
        """Stop current audio playback."""
        if self.wmplayer:
            try:
                self.wmplayer.controls.stop()
                self.wmplayer.close()  # release the media file handle
            except Exception:
                pass

        if pygame.mixer.get_init():
            try:
                pygame.mixer.music.stop()
                # stop() keeps the file open; unload() releases the handle so the
                # file can be moved to quarantine (Windows refuses to move open files).
                pygame.mixer.music.unload()
            except Exception:
                pass

        self.current_filepath = None
        self.is_paused = False
        if self.status_callback:
            self.status_callback("Stopped", False)

    def set_volume(self, volume_val: float):
        """Set volume (0.0 to 1.0)."""
        vol_pct = max(0, min(100, int(volume_val * 100)))
        if self.wmplayer:
            try:
                self.wmplayer.settings.volume = vol_pct
            except Exception:
                pass

        if pygame.mixer.get_init():
            try:
                pygame.mixer.music.set_volume(max(0.0, min(1.0, volume_val)))
            except Exception:
                pass

    def is_playing(self) -> bool:
        """Check if audio is actively playing."""
        if self.backend == "wmplayer" and self.wmplayer:
            try:
                return self.wmplayer.playState == 3  # 3 = wmppsPlaying
            except Exception:
                return False
        if self.backend == "pygame" and pygame.mixer.get_init():
            return pygame.mixer.music.get_busy() and not self.is_paused
        return False
