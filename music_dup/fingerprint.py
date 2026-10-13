import os
import shutil
import sys
import hashlib
import subprocess
import logging
from typing import Optional, Tuple, List, Dict, Any
import acoustid

logger = logging.getLogger(__name__)

_FPCALC_VERIFIED_PATH: Optional[str] = None
_FPCALC_STATUS_CACHE: Optional[Dict[str, Any]] = None

# Seconds to wait for fpcalc on a single file before giving up (corrupt files can hang it).
FPCALC_TIMEOUT = 120


SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0

def _fpcalc_names() -> List[str]:
    """Executable names to look for on this platform."""
    return ["fpcalc.exe", "fpcalc"] if sys.platform == "win32" else ["fpcalc"]


def _is_usable_binary(path: str) -> bool:
    """True if path points at an fpcalc build that can run on this platform."""
    if not path or not os.path.isfile(path):
        return False
    # The bundled Windows build can't run on macOS/Linux; never pick it there.
    if sys.platform != "win32" and path.lower().endswith(".exe"):
        return False
    return True


def find_fpcalc() -> Optional[str]:
    """
    Locate the fpcalc binary. Search order:
      1. FPCALC environment variable (explicit user override)
      2. PyInstaller bundle directory
      3. the project's local bin/ directory
      4. acoustid.FPCALC_COMMAND, if configured
      5. system PATH
      6. the active virtualenv / Python prefix
    """
    names = _fpcalc_names()

    # 1. Explicit override via environment variable
    env_fpcalc = os.environ.get("FPCALC")
    if env_fpcalc:
        resolved = shutil.which(env_fpcalc) or env_fpcalc
        if _is_usable_binary(resolved):
            return resolved

    # 2. PyInstaller frozen bundle directory
    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", "")
        for name in names:
            cand = os.path.join(bundle_dir, name)
            if _is_usable_binary(cand):
                return cand

    # 3. Local bin directory shipped with the project
    local_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
    for root, _, files in os.walk(local_bin):
        for name in names:
            if name in files and _is_usable_binary(os.path.join(root, name)):
                return os.path.join(root, name)

    # 4. acoustid's configured command
    cmd = getattr(acoustid, "FPCALC_COMMAND", None)
    if cmd:
        resolved = shutil.which(cmd)
        if resolved and _is_usable_binary(resolved):
            return resolved

    # 5. System PATH
    for name in names:
        path = shutil.which(name)
        if path and _is_usable_binary(path):
            return path

    # 6. Virtualenv scripts / bin directory
    for sub in ["Scripts", "bin", "."]:
        for name in names:
            cand = os.path.join(sys.prefix, sub, name)
            if _is_usable_binary(cand):
                return cand

    return None


def verify_fpcalc() -> Dict[str, Any]:
    """
    Run `fpcalc -v` once to verify the binary actually executes on this machine.
    """
    global _FPCALC_VERIFIED_PATH, _FPCALC_STATUS_CACHE

    if _FPCALC_STATUS_CACHE is not None:
        return _FPCALC_STATUS_CACHE

    fpcalc_path = find_fpcalc()
    if not fpcalc_path:
        _FPCALC_STATUS_CACHE = {
            "available": False,
            "path": None,
            "version": None,
            "error": "fpcalc binary not found on system PATH or bundle."
        }
        return _FPCALC_STATUS_CACHE

    try:
        # Run fpcalc -v to check if binary executes without missing DLL errors
        res = subprocess.run([fpcalc_path, "-v"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=5, creationflags=SUBPROCESS_FLAGS)
        if res.returncode == 0:
            version_str = res.stdout.strip() or res.stderr.strip()
            acoustid.FPCALC_COMMAND = fpcalc_path
            _FPCALC_VERIFIED_PATH = fpcalc_path
            _FPCALC_STATUS_CACHE = {
                "available": True,
                "path": fpcalc_path,
                "version": version_str,
                "error": None
            }
            return _FPCALC_STATUS_CACHE
        else:
            err_msg = res.stderr.strip() or f"fpcalc exited with code {res.returncode}"
    except Exception as e:
        err_msg = str(e)

    _FPCALC_STATUS_CACHE = {
        "available": False,
        "path": fpcalc_path,
        "version": None,
        "error": f"fpcalc execution failed: {err_msg}"
        + (" (Visual C++ Redistributable may be required)." if sys.platform == "win32" else ".")
    }
    return _FPCALC_STATUS_CACHE


def ensure_fpcalc() -> Optional[str]:
    """Ensure fpcalc path is located and verified."""
    status = verify_fpcalc()
    if status["available"]:
        return status["path"]
    return None


def parse_raw_fpcalc_output(output: str) -> Tuple[float, str]:
    """Parse DURATION and raw FINGERPRINT integer string from fpcalc -raw output."""
    duration = 0.0
    fp_str = ""
    for line in output.splitlines():
        line = line.strip()
        if line.startswith("DURATION="):
            try:
                duration = float(line.split("=", 1)[1])
            except ValueError:
                pass
        elif line.startswith("FINGERPRINT="):
            fp_str = line.split("=", 1)[1]
    return duration, fp_str


def compute_fingerprint(filepath: str) -> Tuple[float, str, str]:
    """
    Computes raw integer chromaprint fingerprint using fpcalc -raw.
    Returns (duration, raw_fingerprint_comma_separated_integers, method).
    """
    fpcalc_path = ensure_fpcalc()

    if fpcalc_path:
        try:
            cmd = [fpcalc_path, "-raw", filepath]
            result = subprocess.run(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                check=True, timeout=FPCALC_TIMEOUT, creationflags=SUBPROCESS_FLAGS,
            )
            duration, raw_fp = parse_raw_fpcalc_output(result.stdout)
            if raw_fp:
                return duration, raw_fp, "chromaprint_raw"
        except Exception as e:
            logger.warning(f"fpcalc -raw failed for {filepath}: {e}")

    return generate_fallback_fingerprint(filepath)


def generate_fallback_fingerprint(filepath: str) -> Tuple[float, str, str]:
    """Fallback fingerprint strategy if fpcalc is unavailable or fails."""
    try:
        filesize = os.path.getsize(filepath)
        with open(filepath, "rb") as f:
            header = f.read(65536)
            if filesize > 131072:
                f.seek(-65536, os.SEEK_END)
                footer = f.read(65536)
            else:
                footer = b""
        
        digest = hashlib.sha256(header + footer).hexdigest()
        fp_str = f"fallback:{filesize}:{digest[:32]}"
        return 0.0, fp_str, "fallback"
    except Exception:
        return 0.0, f"error:{os.path.basename(filepath)}", "error"


def parse_fingerprint_to_ints(fp_str: str) -> List[int]:
    """Parse comma-separated integer string into a list of 32-bit integers."""
    if not fp_str or fp_str.startswith("fallback:") or fp_str.startswith("error:"):
        return []

    if "," in fp_str:
        try:
            return [int(x) for x in fp_str.split(",") if x.strip().lstrip("-").isdigit()]
        except ValueError:
            pass
    elif fp_str.lstrip("-").isdigit():
        return [int(fp_str)]

    return []


# Alignment parameters for comparing raw Chromaprint fingerprints. These match
# the values pyacoustid uses internally.
MAX_BIT_ERROR = 2
MAX_ALIGN_OFFSET = 120


def match_fingerprints(a: List[int], b: List[int]) -> float:
    """
    Compare two raw Chromaprint fingerprints (lists of 32-bit ints) and return
    a similarity score in [0, 1].

    For every pair of frames within MAX_ALIGN_OFFSET of each other, frames that
    differ by at most MAX_BIT_ERROR bits vote for their relative offset. The
    score is the vote count of the best offset divided by the shorter length.
    """
    if not a or not b:
        return 0.0
    asize, bsize = len(a), len(b)
    counts = [0] * (asize + bsize + 1)
    for i in range(asize):
        ai = a[i]
        jbegin = max(0, i - MAX_ALIGN_OFFSET)
        jend = min(bsize, i + MAX_ALIGN_OFFSET)
        for j in range(jbegin, jend):
            if bin((ai ^ b[j]) & 0xFFFFFFFF).count("1") <= MAX_BIT_ERROR:
                counts[i - j + bsize] += 1
    return min(1.0, max(counts) / min(asize, bsize))


def calculate_fingerprint_similarity(fp1: str, fp2: str) -> float:
    """
    Similarity between two stored fingerprint strings, in [0, 1].

    - Raw Chromaprint fingerprints are compared with sliding-offset alignment,
      so the same recording matches across formats and bitrates.
    - Fallback fingerprints (used when fpcalc is unavailable) only match when
      byte-identical, i.e. exact file copies.
    - Error placeholders never match anything.
    """
    if not fp1 or not fp2:
        return 0.0

    if fp1.startswith("error:") or fp2.startswith("error:"):
        return 0.0

    if fp1 == fp2:
        return 1.0

    if fp1.startswith("fallback:") or fp2.startswith("fallback:"):
        return 0.0

    ints1 = parse_fingerprint_to_ints(fp1)
    ints2 = parse_fingerprint_to_ints(fp2)
    if ints1 and ints2:
        return match_fingerprints(ints1, ints2)

    return 0.0
