import os
import sys
import logging
from typing import Optional, Callable

# Initialize pygame mixer safely
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import pygame

logger = logging.getLogger(__name__)


class AudioPlayer:
    """Audio preview player wrapper around pygame.mixer.music."""

    def __init__(self, status_callback: Optional[Callable[[str, bool], None]] = None):
        self.is_initialized = False
        self.current_filepath: Optional[str] = None
        self.is_paused = False
        self.status_callback = status_callback
        
        try:
            pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=2048)
            self.is_initialized = True
        except Exception as e:
            logger.error(f"Failed to initialize pygame.mixer: {e}")

    def load_and_play(self, filepath: str) -> bool:
        """Load and play the given audio file."""
        if not self.is_initialized:
            try:
                pygame.mixer.init()
                self.is_initialized = True
            except Exception as e:
                logger.error(f"Re-init failed: {e}")
                return False

        if not os.path.exists(filepath):
            return False

        try:
            pygame.mixer.music.stop()
            pygame.mixer.music.load(filepath)
            pygame.mixer.music.play()
            self.current_filepath = filepath
            self.is_paused = False

            if self.status_callback:
                self.status_callback(os.path.basename(filepath), True)
            return True
        except Exception as e:
            logger.error(f"Error playing {filepath}: {e}")
            if self.status_callback:
                self.status_callback(f"Playback Error: {os.path.basename(filepath)}", False)
            return False

    def toggle_play_pause(self) -> bool:
        """Toggle between play and pause."""
        if not self.is_initialized or not self.current_filepath:
            return False

        if self.is_paused:
            pygame.mixer.music.unpause()
            self.is_paused = False
            if self.status_callback:
                self.status_callback(os.path.basename(self.current_filepath), True)
            return True
        else:
            pygame.mixer.music.pause()
            self.is_paused = True
            if self.status_callback:
                self.status_callback(f"Paused: {os.path.basename(self.current_filepath)}", False)
            return False

    def stop(self):
        """Stop current audio playback."""
        if self.is_initialized:
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
        self.current_filepath = None
        self.is_paused = False
        if self.status_callback:
            self.status_callback("Stopped", False)

    def set_volume(self, volume_val: float):
        """Set volume (0.0 to 1.0)."""
        if self.is_initialized:
            try:
                pygame.mixer.music.set_volume(max(0.0, min(1.0, volume_val)))
            except Exception:
                pass

    def is_playing(self) -> bool:
        """Check if audio is actively playing."""
        if not self.is_initialized:
            return False
        return pygame.mixer.music.get_busy() and not self.is_paused
