import os
import shutil
import sys
import hashlib
import subprocess
import logging
from typing import Optional, Tuple, List, Dict, Any
import acoustid

logger = logging.getLogger(__name__)

FPCALC_NAMES = ["fpcalc", "fpcalc.exe"]
_FPCALC_VERIFIED_PATH: Optional[str] = None
_FPCALC_STATUS_CACHE: Optional[Dict[str, Any]] = None


SUBPROCESS_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000) if sys.platform == "win32" else 0

def find_fpcalc() -> Optional[str]:
    """
    Search for fpcalc binary in PyInstaller bundle, PATH, environment variables, virtual environment, and local directories.
    """
    # 0. Check PyInstaller frozen bundle directory
    if getattr(sys, 'frozen', False):
        bundle_dir = getattr(sys, '_MEIPASS', '')
        for name in FPCALC_NAMES:
            cand = os.path.join(bundle_dir, name)
            if os.path.exists(cand):
                return cand

    # 1. Check local bin directory
    local_bin = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "bin")
    for root, _, files in os.walk(local_bin):
        for name in FPCALC_NAMES:
            if name in files:
                return os.path.join(root, name)

    # 2. Check if acoustid already configured FPCALC_COMMAND
    if hasattr(acoustid, "FPCALC_COMMAND") and acoustid.FPCALC_COMMAND:
        cmd = acoustid.FPCALC_COMMAND
        if shutil.which(cmd) or os.path.exists(cmd):
            return cmd

    # 3. Check environment variable FPCALC
    env_fpcalc = os.environ.get("FPCALC")
    if env_fpcalc and (shutil.which(env_fpcalc) or os.path.exists(env_fpcalc)):
        return env_fpcalc

    # 4. Check system PATH
    for name in FPCALC_NAMES:
        path = shutil.which(name)
        if path:
            return path

    # 5. Check virtualenv scripts or binary directory
    prefix = sys.prefix
    for sub in ["Scripts", "bin", "."]:
        for name in FPCALC_NAMES:
            cand = os.path.join(prefix, sub, name)
            if os.path.exists(cand):
                return cand

    return None


def verify_fpcalc() -> Dict[str, Any]:
    """
    Test executing fpcalc -v to verify the binary runs on the host Windows environment.
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
        "error": f"fpcalc execution failed: {err_msg} (Visual C++ Redistributable may be required)."
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
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, check=True, creationflags=SUBPROCESS_FLAGS)
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

    return []


def calculate_fingerprint_similarity(fp1: str, fp2: str) -> float:
    """
    Calculate cross-format acoustic fingerprint similarity using sliding offset bitwise comparison.
    """
    if not fp1 or not fp2:
        return 0.0

    if fp1 == fp2:
        return 1.0

    if fp1.startswith("fallback:") or fp2.startswith("fallback:"):
        return 1.0 if fp1 == fp2 else 0.0

    ints1 = parse_fingerprint_to_ints(fp1)
    ints2 = parse_fingerprint_to_ints(fp2)

    if ints1 and ints2:
        try:
            return float(acoustid._match_fingerprints(ints1, ints2))
        except Exception as e:
            logger.warning(f"Error matching fingerprints: {e}")

    return 1.0 if fp1 == fp2 else 0.0
