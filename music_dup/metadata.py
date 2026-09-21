import os
from dataclasses import dataclass
from typing import Optional, Dict, Any
import mutagen

LOSSLESS_EXTENSIONS = {".flac", ".wav", ".aiff", ".aif", ".alac", ".ape", ".wv"}

@dataclass
class AudioMetadata:
    filepath: str
    filesize: int
    format_ext: str
    duration: float  # seconds
    bitrate: int  # kbps
    sample_rate: int  # Hz
    channels: int
    bits_per_sample: int  # e.g., 16, 24, 32 or 0 if N/A
    is_lossless: bool
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    quality_score: float = 0.0
    quality_badge: str = ""

    def calculate_quality_score(self) -> float:
        """
        Calculate audio quality score based on format, bitrate, sample rate, bit depth, and channels.
        Higher score = better quality.
        """
        score = 0.0
        
        # Lossless tier bonus (100,000 points)
        if self.is_lossless:
            score += 100000.0
            
        # Bitrate score (100 points per kbps)
        # Note: For FLAC/WAV bitrate is often derived from (sample_rate * channels * bits_per_sample / 1000)
        effective_bitrate = self.bitrate
        if self.is_lossless and effective_bitrate <= 0:
            effective_bitrate = int((self.sample_rate * self.channels * (self.bits_per_sample or 16)) / 1000)
        score += max(0, effective_bitrate) * 100.0
        
        # Sample rate score (0.1 point per Hz, e.g., 44100 -> 4410)
        score += (self.sample_rate / 10.0)
        
        # Bit depth score (500 points per bit above 16)
        if self.bits_per_sample > 0:
            score += self.bits_per_sample * 500.0
            
        # Channels score
        score += self.channels * 100.0
        
        # Metadata completeness bonus (clean metadata is a secondary preference)
        if self.title:
            score += 200.0
        if self.artist:
            score += 200.0
        if self.album:
            score += 200.0
            
        self.quality_score = score
        self.quality_badge = self.format_quality_badge()
        return score

    def format_quality_badge(self) -> str:
        """Format a human-readable quality badge string."""
        type_str = "Lossless" if self.is_lossless else "Lossy"
        ext = self.format_ext.upper().lstrip(".")
        sr_khz = self.sample_rate / 1000.0 if self.sample_rate else 0.0
        
        details = []
        if self.is_lossless and self.bits_per_sample > 0:
            details.append(f"{self.bits_per_sample}-bit")
        if self.bitrate > 0 and not self.is_lossless:
            details.append(f"{self.bitrate}kbps")
        elif self.bitrate > 0 and self.is_lossless:
            details.append(f"{self.bitrate}kbps")
            
        if sr_khz > 0:
            details.append(f"{sr_khz:.1f}kHz")
            
        detail_str = "/".join(details) if details else ""
        return f"{ext} {detail_str} ({type_str})" if detail_str else f"{ext} ({type_str})"


def extract_audio_metadata(filepath: str) -> AudioMetadata:
    """
    Extract audio metadata from file using mutagen.
    """
    filesize = os.path.getsize(filepath)
    ext = os.path.splitext(filepath)[1].lower()
    is_lossless = ext in LOSSLESS_EXTENSIONS

    duration = 0.0
    bitrate = 0
    sample_rate = 0
    channels = 2
    bits_per_sample = 0
    title = None
    artist = None
    album = None

    try:
        audio = mutagen.File(filepath)
        if audio is not None:
            # Extract info
            if hasattr(audio, "info") and audio.info is not None:
                info = audio.info
                duration = float(getattr(info, "length", 0.0))
                sample_rate = int(getattr(info, "sample_rate", 0))
                channels = int(getattr(info, "channels", 2))
                
                # Bitrate (bps -> kbps)
                raw_bitrate = getattr(info, "bitrate", 0)
                if raw_bitrate:
                    bitrate = int(raw_bitrate / 1000)
                
                # Bit depth / bits per sample
                bits_per_sample = int(getattr(info, "bits_per_sample", 0))

                # Special codec checks
                codec = getattr(info, "codec", "").lower() if hasattr(info, "codec") else ""
                if "alac" in codec or "flac" in codec:
                    is_lossless = True

            # Extract tags
            if audio.tags:
                tags = audio.tags
                # Helper to safely extract string tag
                def get_tag_val(keys):
                    for k in keys:
                        if k in tags:
                            val = tags[k]
                            if isinstance(val, list) and len(val) > 0:
                                return str(val[0])
                            elif isinstance(val, (str, int)):
                                return str(val)
                    return None

                title = get_tag_val(["TIT2", "title", "\xa9nam", "TITLE"])
                artist = get_tag_val(["TPE1", "artist", "\xa9ART", "ARTIST"])
                album = get_tag_val(["TALB", "album", "\xa9alb", "ALBUM"])
    except Exception as e:
        # Fallback for unparseable metadata
        pass

    # Default duration fallback if zero
    if duration <= 0:
        duration = 0.0

    meta = AudioMetadata(
        filepath=filepath,
        filesize=filesize,
        format_ext=ext,
        duration=duration,
        bitrate=bitrate,
        sample_rate=sample_rate,
        channels=channels,
        bits_per_sample=bits_per_sample,
        is_lossless=is_lossless,
        title=title,
        artist=artist,
        album=album,
    )
    meta.calculate_quality_score()
    return meta
