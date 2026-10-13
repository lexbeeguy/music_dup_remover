import os

# Windows' classic MAX_PATH is 260 characters; leave headroom for "_dupN" suffixes.
LONG_PATH_THRESHOLD = 240
_EXTENDED_PREFIX = "\\\\?\\"


def normalize_long_path(path: str) -> str:
    """
    Return an absolute path that file APIs can open even when it's long.

    On Windows, paths over ~240 characters get the extended-length prefix
    (\\\\?\\) so they work without the LongPathsEnabled registry setting.
    Elsewhere the path is just made absolute. Use this for filesystem calls
    only; store and display the plain path.
    """
    path = os.path.abspath(path)
    if os.name == "nt" and len(path) > LONG_PATH_THRESHOLD and not path.startswith(_EXTENDED_PREFIX):
        return _EXTENDED_PREFIX + path
    return path
