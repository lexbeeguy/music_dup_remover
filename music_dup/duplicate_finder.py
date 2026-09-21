import uuid
import os
import re
from difflib import SequenceMatcher
from typing import List, Dict, Any, Tuple
from music_dup.db import Database
from music_dup.fingerprint import calculate_fingerprint_similarity


class UnionFind:
    def __init__(self, elements):
        self.parent = {e: e for e in elements}

    def find(self, i):
        if self.parent[i] == i:
            return i
        self.parent[i] = self.find(self.parent[i])
        return self.parent[i]

    def union(self, i, j):
        root_i = self.find(i)
        root_j = self.find(j)
        if root_i != root_j:
            self.parent[root_i] = root_j


def normalize_string(s: str) -> str:
    """Normalize string for fuzzy title/artist comparison."""
    if not s:
        return ""
    # If path, extract filename without extension first
    if "/" in s or "\\" in s or "." in s:
        s = os.path.splitext(os.path.basename(s))[0]
    # Lowercase, remove track numbers (e.g., 01 -, 01.), punctuation, extra whitespace
    s = s.lower()
    s = re.sub(r"^\d+[\s\.\-_]+", "", s)
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.split())


def is_metadata_duplicate(f1: Dict[str, Any], f2: Dict[str, Any], duration_tolerance: float) -> bool:
    """
    Check if two files are duplicates based on normalized title/artist tags & duration.
    """
    dur1 = f1["duration"]
    dur2 = f2["duration"]

    # Must have matching duration within tolerance
    if dur1 > 0 and dur2 > 0:
        if abs(dur1 - dur2) > duration_tolerance:
            return False

    title1 = normalize_string(f1.get("title") or "")
    title2 = normalize_string(f2.get("title") or "")

    # If title tag is missing, fallback to cleaned filename
    if not title1:
        title1 = normalize_string(f1["filepath"])
    if not title2:
        title2 = normalize_string(f2["filepath"])

    if not title1 or not title2:
        return False

    # Check title similarity
    title_ratio = SequenceMatcher(None, title1, title2).ratio()
    if title_ratio >= 0.90:
        artist1 = normalize_string(f1.get("artist") or "")
        artist2 = normalize_string(f2.get("artist") or "")
        if artist1 and artist2:
            artist_ratio = SequenceMatcher(None, artist1, artist2).ratio()
            return artist_ratio >= 0.80
        return True

    return False


def find_and_rank_duplicates(
    db: Database,
    similarity_threshold: float = 0.70,
    duration_tolerance: float = 3.5
) -> List[Dict[str, Any]]:
    """
    Scans DB file records, identifies cross-format acoustic duplicate groups using
    chromaprint sliding-window fingerprint similarity and metadata comparison,
    ranks tracks within each group by quality score, and saves groups to DB.
    """
    files = db.get_all_scanned_files()
    if not files:
        return []

    file_ids = [f["id"] for f in files]
    uf = UnionFind(file_ids)

    # 1. Compare file pairs to construct duplicate clusters
    n = len(files)
    for i in range(n):
        f1 = files[i]
        fp1 = f1["fingerprint"]
        dur1 = f1["duration"]
        
        for j in range(i + 1, n):
            f2 = files[j]
            fp2 = f2["fingerprint"]
            dur2 = f2["duration"]

            # Quick duration filter (skip if duration differs by more than tolerance)
            if dur1 > 0 and dur2 > 0:
                if abs(dur1 - dur2) > duration_tolerance:
                    continue

            is_dup = False

            # Check 1: Acoustic chromaprint fingerprint similarity
            similarity = calculate_fingerprint_similarity(fp1, fp2)
            if similarity >= similarity_threshold:
                is_dup = True
            # Check 2: Metadata tag & duration similarity
            elif is_metadata_duplicate(f1, f2, duration_tolerance):
                is_dup = True

            if is_dup:
                uf.union(f1["id"], f2["id"])

    # 2. Group files by root component
    clusters: Dict[int, List[Dict[str, Any]]] = {}
    for f in files:
        root = uf.find(f["id"])
        if root not in clusters:
            clusters[root] = []
        clusters[root].append(f)

    # Filter out singletons (groups with only 1 file are not duplicates)
    duplicate_clusters = [files_list for files_list in clusters.values() if len(files_list) > 1]

    # 3. Clear old duplicate groups in DB and write newly identified groups
    db.clear_duplicate_groups()

    results = []
    for cluster in duplicate_clusters:
        # Rank files within cluster by quality_score descending
        # Secondary tie-breaker: filesize descending
        sorted_files = sorted(
            cluster,
            key=lambda x: (x["quality_score"], x["filesize"]),
            reverse=True
        )

        group_id = f"grp_{uuid.uuid4().hex[:10]}"
        file_rankings = []
        
        for rank_idx, f in enumerate(sorted_files, 1):
            file_rankings.append((f["id"], rank_idx))
            f["rank"] = rank_idx
            f["is_quarantined"] = f.get("is_quarantined", 0)

        db.save_duplicate_group(group_id, file_rankings)

        wasted_size = sum(f["filesize"] for f in sorted_files[1:])
        results.append({
            "group_id": group_id,
            "master_file": sorted_files[0],
            "duplicates": sorted_files[1:],
            "all_files": sorted_files,
            "wasted_size": wasted_size
        })

    return results
