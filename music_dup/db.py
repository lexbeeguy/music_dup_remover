import sqlite3
import os
import time
from typing import Optional, List, Dict, Any, Tuple
from music_dup.metadata import AudioMetadata

DEFAULT_DB_PATH = "music_dup.db"


class Database:
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        self.db_path = os.path.abspath(db_path)
        self._init_db()

    def get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Files metadata table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                filepath TEXT UNIQUE NOT NULL,
                filesize INTEGER NOT NULL,
                mtime REAL NOT NULL,
                format_ext TEXT NOT NULL,
                duration REAL NOT NULL,
                bitrate INTEGER NOT NULL,
                sample_rate INTEGER NOT NULL,
                channels INTEGER NOT NULL,
                bits_per_sample INTEGER NOT NULL,
                is_lossless INTEGER NOT NULL,
                title TEXT,
                artist TEXT,
                album TEXT,
                fingerprint TEXT,
                fp_method TEXT,
                quality_score REAL NOT NULL,
                quality_badge TEXT NOT NULL,
                scanned_at REAL NOT NULL
            )
            """)

            # Duplicate groups table
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS duplicate_groups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                group_id TEXT NOT NULL,
                file_id INTEGER NOT NULL,
                rank INTEGER NOT NULL,
                is_quarantined INTEGER DEFAULT 0,
                FOREIGN KEY(file_id) REFERENCES files(id) ON DELETE CASCADE
            )
            """)

            # Quarantine history log
            cursor.execute("""
            CREATE TABLE IF NOT EXISTS quarantine_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_id INTEGER NOT NULL,
                original_path TEXT NOT NULL,
                quarantine_path TEXT NOT NULL,
                group_id TEXT NOT NULL,
                quarantined_at REAL NOT NULL,
                FOREIGN KEY(file_id) REFERENCES files(id)
            )
            """)

            # Indexes
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_path ON files(filepath);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_duration ON files(duration);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_fingerprint ON files(fingerprint);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_files_lookup ON files(filepath, filesize, mtime);")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_group ON duplicate_groups(group_id);")
            
            conn.commit()

    def get_cached_file(self, filepath: str, filesize: int, mtime: float) -> Optional[Dict[str, Any]]:
        """
        Check if file metadata and fingerprint are already cached in DB and unchanged.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM files WHERE filepath = ? AND filesize = ? AND ABS(mtime - ?) < 0.001
            """, (filepath, filesize, mtime))
            row = cursor.fetchone()
            if row:
                return dict(row)
            return None

    def upsert_file(self, meta: AudioMetadata, fingerprint: str, fp_method: str) -> int:
        """
        Insert or update file record in database.
        """
        mtime = os.path.getmtime(meta.filepath)
        now = time.time()

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO files (
                    filepath, filesize, mtime, format_ext, duration, bitrate,
                    sample_rate, channels, bits_per_sample, is_lossless,
                    title, artist, album, fingerprint, fp_method,
                    quality_score, quality_badge, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filepath) DO UPDATE SET
                    filesize=excluded.filesize,
                    mtime=excluded.mtime,
                    format_ext=excluded.format_ext,
                    duration=excluded.duration,
                    bitrate=excluded.bitrate,
                    sample_rate=excluded.sample_rate,
                    channels=excluded.channels,
                    bits_per_sample=excluded.bits_per_sample,
                    is_lossless=excluded.is_lossless,
                    title=excluded.title,
                    artist=excluded.artist,
                    album=excluded.album,
                    fingerprint=excluded.fingerprint,
                    fp_method=excluded.fp_method,
                    quality_score=excluded.quality_score,
                    quality_badge=excluded.quality_badge,
                    scanned_at=excluded.scanned_at
            """, (
                meta.filepath, meta.filesize, mtime, meta.format_ext, meta.duration,
                meta.bitrate, meta.sample_rate, meta.channels, meta.bits_per_sample,
                1 if meta.is_lossless else 0, meta.title, meta.artist, meta.album,
                fingerprint, fp_method, meta.quality_score, meta.quality_badge, now
            ))
            conn.commit()
            
            cursor.execute("SELECT id FROM files WHERE filepath = ?", (meta.filepath,))
            return cursor.fetchone()["id"]

    def upsert_files_batch(self, items: List[Tuple[AudioMetadata, str, str]]):
        """
        Batch insert or update multiple file records in a single atomic transaction.
        items is a list of tuples: (AudioMetadata, fingerprint_str, fp_method_str)
        """
        if not items:
            return

        now = time.time()
        rows = []
        for meta, fingerprint, fp_method in items:
            try:
                mtime = os.path.getmtime(meta.filepath)
            except Exception:
                mtime = now

            rows.append((
                meta.filepath, meta.filesize, mtime, meta.format_ext, meta.duration,
                meta.bitrate, meta.sample_rate, meta.channels, meta.bits_per_sample,
                1 if meta.is_lossless else 0, meta.title, meta.artist, meta.album,
                fingerprint, fp_method, meta.quality_score, meta.quality_badge, now
            ))

        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.executemany("""
                INSERT INTO files (
                    filepath, filesize, mtime, format_ext, duration, bitrate,
                    sample_rate, channels, bits_per_sample, is_lossless,
                    title, artist, album, fingerprint, fp_method,
                    quality_score, quality_badge, scanned_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(filepath) DO UPDATE SET
                    filesize=excluded.filesize,
                    mtime=excluded.mtime,
                    format_ext=excluded.format_ext,
                    duration=excluded.duration,
                    bitrate=excluded.bitrate,
                    sample_rate=excluded.sample_rate,
                    channels=excluded.channels,
                    bits_per_sample=excluded.bits_per_sample,
                    is_lossless=excluded.is_lossless,
                    title=excluded.title,
                    artist=excluded.artist,
                    album=excluded.album,
                    fingerprint=excluded.fingerprint,
                    fp_method=excluded.fp_method,
                    quality_score=excluded.quality_score,
                    quality_badge=excluded.quality_badge,
                    scanned_at=excluded.scanned_at
            """, rows)
            conn.commit()

    def clear_duplicate_groups(self):
        """Reset all computed duplicate groups."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM duplicate_groups")
            conn.commit()

    def save_duplicate_group(self, group_id: str, file_rankings: List[Tuple[int, int]]):
        """
        Save a duplicate group with file IDs and their ranks (rank 1 = best quality).
        file_rankings is a list of tuples: (file_id, rank)
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            for file_id, rank in file_rankings:
                cursor.execute("""
                    INSERT INTO duplicate_groups (group_id, file_id, rank)
                    VALUES (?, ?, ?)
                """, (group_id, file_id, rank))
            conn.commit()

    def get_all_scanned_files(self) -> List[Dict[str, Any]]:
        """Return all scanned file records from DB."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM files WHERE fingerprint IS NOT NULL AND fingerprint != ''")
            return [dict(r) for r in cursor.fetchall()]

    def get_duplicate_groups_summary(self) -> List[Dict[str, Any]]:
        """
        Return structured duplicate groups with member file details ranked by quality.
        """
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT g.group_id, g.rank, g.is_quarantined, f.*
                FROM duplicate_groups g
                JOIN files f ON g.file_id = f.id
                ORDER BY g.group_id, g.rank ASC
            """)
            rows = cursor.fetchall()

        groups_map: Dict[str, List[Dict[str, Any]]] = {}
        for r in rows:
            d = dict(r)
            gid = d["group_id"]
            if gid not in groups_map:
                groups_map[gid] = []
            groups_map[gid].append(d)

        results = []
        for gid, files in groups_map.items():
            if len(files) > 1:
                master = files[0]
                total_size = sum(f["filesize"] for f in files)
                wasted_size = sum(f["filesize"] for f in files[1:])
                results.append({
                    "group_id": gid,
                    "master_file": master,
                    "all_files": files,
                    "total_files": len(files),
                    "total_size": total_size,
                    "wasted_size": wasted_size
                })
        return results

    def record_quarantine(self, file_id: int, original_path: str, quarantine_path: str, group_id: str):
        """Record quarantine event in DB."""
        now = time.time()
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO quarantine_history (file_id, original_path, quarantine_path, group_id, quarantined_at)
                VALUES (?, ?, ?, ?, ?)
            """, (file_id, original_path, quarantine_path, group_id, now))
            
            cursor.execute("""
                UPDATE duplicate_groups SET is_quarantined = 1 WHERE file_id = ?
            """, (file_id,))
            
            # Update filepath in files table to point to quarantine location
            cursor.execute("""
                UPDATE files SET filepath = ? WHERE id = ?
            """, (quarantine_path, file_id))
            
            conn.commit()

    def record_restore(self, file_id: int, original_path: str):
        """Record restore event in DB."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM quarantine_history WHERE file_id = ?", (file_id,))
            cursor.execute("UPDATE duplicate_groups SET is_quarantined = 0 WHERE file_id = ?", (file_id,))
            cursor.execute("UPDATE files SET filepath = ? WHERE id = ?", (original_path, file_id))
            conn.commit()

    def get_quarantine_history(self) -> List[Dict[str, Any]]:
        """Return active quarantine records."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT q.*, f.title, f.artist, f.format_ext, f.quality_badge, f.filesize
                FROM quarantine_history q
                JOIN files f ON q.file_id = f.id
                ORDER BY q.quarantined_at DESC
            """)
            return [dict(r) for r in cursor.fetchall()]

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistical overview."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*), SUM(filesize) FROM files")
            total_files, total_size = cursor.fetchone()

            cursor.execute("SELECT COUNT(DISTINCT group_id) FROM duplicate_groups")
            total_groups = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM quarantine_history")
            quarantined_count = cursor.fetchone()[0]

            groups = self.get_duplicate_groups_summary()
            total_wasted_space = sum(g["wasted_size"] for g in groups)

            return {
                "db_path": self.db_path,
                "total_files": total_files or 0,
                "total_size": total_size or 0,
                "duplicate_groups": total_groups or 0,
                "quarantined_count": quarantined_count or 0,
                "wasted_space": total_wasted_space
            }

    def reset_db(self):
        """Clear all tables in database."""
        with self.get_connection() as conn:
            conn.execute("DELETE FROM quarantine_history")
            conn.execute("DELETE FROM duplicate_groups")
            conn.execute("DELETE FROM files")
            conn.commit()
