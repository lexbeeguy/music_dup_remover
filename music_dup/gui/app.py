import os
import sys
import threading
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import List, Dict, Any, Optional

import customtkinter as ctk

from music_dup import __version__
from music_dup.db import Database, DEFAULT_DB_PATH
from music_dup.scanner import scan_directory
from music_dup.duplicate_finder import find_and_rank_duplicates
from music_dup.quarantine import quarantine_duplicates, restore_quarantined_files
from music_dup.gui.player import AudioPlayer
from music_dup.ui import format_bytes


# Configure CustomTkinter defaults
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")


class MusicDupApp(ctk.CTk):
    def __init__(self, db_path: str = DEFAULT_DB_PATH):
        super().__init__()

        self.title(f"Music Duplicate Management Tool (v{__version__})")
        self.geometry("1100x780")
        self.minsize(900, 600)

        self.db = Database(db_path=db_path)
        
        # Audio Player initialization
        self.player = AudioPlayer(status_callback=self._update_player_status)

        # State storage
        self.scan_directory_path: str = ""
        self.is_scanning: bool = False
        self.current_page: int = 1
        self.page_size: int = 50
        self.duplicate_groups: List[Dict[str, Any]] = []
        self.candidate_checkboxes: Dict[int, ctk.CTkCheckBox] = {}
        self.quarantine_checkboxes: Dict[int, ctk.CTkCheckBox] = {}
        self.candidate_file_map: Dict[int, Dict[str, Any]] = {}
        self.quarantined_file_map: Dict[int, Dict[str, Any]] = {}

        # Build UI layout
        self._create_header()
        self._create_tabview()
        self._create_player_bar()

        # Load initial database state
        self.refresh_duplicates_view()
        self.refresh_quarantine_view()
        self.refresh_stats_view()

    # -------------------------------------------------------------------------
    # UI Header & Player Bar
    # -------------------------------------------------------------------------
    def _create_header(self):
        header_frame = ctk.CTkFrame(self, corner_radius=0, height=50, fg_color=("gray85", "gray15"))
        header_frame.pack(side="top", fill="x", padx=0, pady=0)

        title_label = ctk.CTkLabel(
            header_frame,
            text=f"🎵 Music Duplicate Finder v{__version__}",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        title_label.pack(side="left", padx=20, pady=10)

        theme_switch = ctk.CTkSwitch(
            header_frame,
            text="Dark Mode",
            command=self._toggle_theme,
            onvalue="Dark",
            offvalue="Light"
        )
        theme_switch.select()
        theme_switch.pack(side="right", padx=20, pady=10)

    def _create_player_bar(self):
        """Persistent bottom audio preview player bar."""
        player_frame = ctk.CTkFrame(self, corner_radius=0, height=55, fg_color=("gray80", "gray20"))
        player_frame.pack(side="bottom", fill="x")

        self.player_track_label = ctk.CTkLabel(
            player_frame,
            text="🎧 Audio Preview: Select a track to play",
            font=ctk.CTkFont(size=12, weight="normal"),
            anchor="w"
        )
        self.player_track_label.pack(side="left", padx=15, pady=12, fill="x", expand=True)

        self.play_pause_btn = ctk.CTkButton(
            player_frame,
            text="⏯ Play/Pause",
            width=90,
            height=30,
            command=self._on_toggle_play_pause
        )
        self.play_pause_btn.pack(side="left", padx=5, pady=10)

        stop_btn = ctk.CTkButton(
            player_frame,
            text="⏹ Stop",
            width=70,
            height=30,
            fg_color="gray40",
            hover_color="gray30",
            command=self._on_stop_player
        )
        stop_btn.pack(side="left", padx=5, pady=10)

        vol_label = ctk.CTkLabel(player_frame, text="🔊", font=ctk.CTkFont(size=14))
        vol_label.pack(side="left", padx=(15, 5))

        self.vol_slider = ctk.CTkSlider(
            player_frame,
            from_=0.0,
            to=1.0,
            number_of_steps=20,
            width=100,
            command=self._on_volume_change
        )
        self.vol_slider.set(0.8)
        self.vol_slider.pack(side="left", padx=(0, 15))

    def _update_player_status(self, track_name: str, is_playing: bool):
        status_symbol = "▶ Playing" if is_playing else "⏸ Paused"
        self.player_track_label.configure(text=f"🎧 Audio Preview ({status_symbol}): {track_name}")

    def _on_toggle_play_pause(self):
        self.player.toggle_play_pause()

    def _on_stop_player(self):
        self.player.stop()
        self.player_track_label.configure(text="🎧 Audio Preview: Stopped")

    def _on_volume_change(self, val: float):
        self.player.set_volume(val)

    def _toggle_theme(self):
        mode = ctk.get_appearance_mode()
        ctk.set_appearance_mode("Light" if mode == "Dark" else "Dark")

    # -------------------------------------------------------------------------
    # Tab View Navigation
    # -------------------------------------------------------------------------
    def _create_tabview(self):
        self.tabview = ctk.CTkTabview(self, corner_radius=8)
        self.tabview.pack(side="top", fill="both", expand=True, padx=15, pady=10)

        self.tab_scan = self.tabview.add("Scanner & Duplicates")
        self.tab_quarantine = self.tabview.add("Quarantine Manager")
        self.tab_stats = self.tabview.add("Statistics")

        self._setup_scan_tab()
        self._setup_quarantine_tab()
        self._setup_stats_tab()

    # -------------------------------------------------------------------------
    # TAB 1: Scanner & Duplicates View
    # -------------------------------------------------------------------------
    def _setup_scan_tab(self):
        # Controls Frame (Directory Picker & Parameters)
        ctrl_frame = ctk.CTkFrame(self.tab_scan, corner_radius=6)
        ctrl_frame.pack(side="top", fill="x", padx=10, pady=10)

        # Folder Picker
        path_label = ctk.CTkLabel(ctrl_frame, text="Music Directory:", font=ctk.CTkFont(weight="bold"))
        path_label.grid(row=0, column=0, padx=10, pady=10, sticky="w")

        self.dir_entry = ctk.CTkEntry(ctrl_frame, placeholder_text="Select folder to scan...", width=380)
        self.dir_entry.grid(row=0, column=1, padx=5, pady=10, sticky="ew")

        browse_btn = ctk.CTkButton(ctrl_frame, text="📁 Browse...", width=90, command=self._browse_directory)
        browse_btn.grid(row=0, column=2, padx=5, pady=10)

        self.start_scan_btn = ctk.CTkButton(
            ctrl_frame, text="⚡ Start Scan", width=120, fg_color="#2FA572", hover_color="#1E7852",
            command=self._start_background_scan
        )
        self.start_scan_btn.grid(row=0, column=3, padx=10, pady=10)

        # Advanced options (Similarity & Tolerance)
        sim_label = ctk.CTkLabel(ctrl_frame, text="Fingerprint Similarity Threshold:")
        sim_label.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="w")

        self.sim_slider = ctk.CTkSlider(ctrl_frame, from_=0.50, to=0.95, number_of_steps=9, width=200, command=self._on_sim_slider_change)
        self.sim_slider.set(0.85)
        self.sim_slider.grid(row=1, column=1, padx=5, pady=(0, 10), sticky="w")

        self.sim_val_label = ctk.CTkLabel(ctrl_frame, text="0.85 (85%)", font=ctk.CTkFont(weight="bold"))
        self.sim_val_label.grid(row=1, column=1, padx=(220, 5), pady=(0, 10), sticky="w")

        tol_label = ctk.CTkLabel(ctrl_frame, text="Duration Tolerance (s):")
        tol_label.grid(row=1, column=2, padx=10, pady=(0, 10), sticky="e")

        self.tol_entry = ctk.CTkEntry(ctrl_frame, width=60)
        self.tol_entry.insert(0, "3.5")
        self.tol_entry.grid(row=1, column=3, padx=10, pady=(0, 10), sticky="w")

        ctrl_frame.columnconfigure(1, weight=1)

        # Scan Progress Frame
        self.progress_frame = ctk.CTkFrame(self.tab_scan, corner_radius=6)
        self.progress_frame.pack(side="top", fill="x", padx=10, pady=(0, 10))

        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=12)
        self.progress_bar.set(0)
        self.progress_bar.pack(side="top", fill="x", padx=15, pady=(10, 5))

        self.status_label = ctk.CTkLabel(
            self.progress_frame, text="Ready. Select a directory and click 'Start Scan'.",
            font=ctk.CTkFont(size=12, slant="italic")
        )
        self.status_label.pack(side="top", padx=15, pady=(0, 10), anchor="w")

        # Duplicate Results Toolbar (Granular Selection Actions)
        results_bar = ctk.CTkFrame(self.tab_scan, corner_radius=0, fg_color="transparent")
        results_bar.pack(side="top", fill="x", padx=10, pady=(0, 5))

        self.results_summary_label = ctk.CTkLabel(
            results_bar, text="Acoustic Duplicate Clusters", font=ctk.CTkFont(size=15, weight="bold")
        )
        self.results_summary_label.pack(side="left", padx=5)

        select_all_btn = ctk.CTkButton(results_bar, text="Select All Candidates", width=140, command=self._select_all_candidates)
        select_all_btn.pack(side="left", padx=5)

        deselect_all_btn = ctk.CTkButton(results_bar, text="Deselect All", width=90, fg_color="gray50", hover_color="gray40", command=self._deselect_all_candidates)
        deselect_all_btn.pack(side="left", padx=5)

        self.quarantine_sel_btn = ctk.CTkButton(
            results_bar, text="📥 Quarantine Selected Files", width=180, fg_color="#D32F2F", hover_color="#9A0007",
            command=self._quarantine_selected_candidates
        )
        self.quarantine_sel_btn.pack(side="right", padx=5)

        # Scrollable Duplicate Groups Container
        self.clusters_scroll = ctk.CTkScrollableFrame(self.tab_scan, label_text="Identified Duplicates")
        self.clusters_scroll.pack(side="top", fill="both", expand=True, padx=10, pady=5)

        # Pagination Control Bar
        self.page_frame = ctk.CTkFrame(self.tab_scan, corner_radius=0, fg_color="transparent")
        self.page_frame.pack(side="bottom", fill="x", padx=10, pady=5)

        self.prev_page_btn = ctk.CTkButton(
            self.page_frame, text="◀ Previous Page", width=120, command=self._on_prev_page
        )
        self.prev_page_btn.pack(side="left", padx=5)

        self.page_label = ctk.CTkLabel(
            self.page_frame, text="Page 1 of 1", font=ctk.CTkFont(size=12, weight="bold")
        )
        self.page_label.pack(side="left", padx=20)

        self.next_page_btn = ctk.CTkButton(
            self.page_frame, text="Next Page ▶", width=120, command=self._on_next_page
        )
        self.next_page_btn.pack(side="left", padx=5)

    def _on_prev_page(self):
        if self.current_page > 1:
            self.current_page -= 1
            self.refresh_duplicates_view()

    def _on_next_page(self):
        max_page = max(1, (len(self.duplicate_groups) + self.page_size - 1) // self.page_size)
        if self.current_page < max_page:
            self.current_page += 1
            self.refresh_duplicates_view()

    def _on_sim_slider_change(self, val: float):
        self.sim_val_label.configure(text=f"{val:.2f} ({int(val * 100)}%)")

    def _browse_directory(self):
        folder = filedialog.askdirectory(title="Select Music Directory")
        if folder:
            self.dir_entry.delete(0, tk.END)
            self.dir_entry.insert(0, folder)
            self.scan_directory_path = folder

    def _select_all_candidates(self):
        for cb in self.candidate_checkboxes.values():
            cb.select()

    def _deselect_all_candidates(self):
        for cb in self.candidate_checkboxes.values():
            cb.deselect()

    # -------------------------------------------------------------------------
    # Background Scan Execution
    # -------------------------------------------------------------------------
    def _start_background_scan(self):
        directory = self.dir_entry.get().strip()
        if not directory or not os.path.exists(directory):
            messagebox.showerror("Invalid Directory", "Please select a valid directory path to scan.")
            return

        try:
            similarity = float(self.sim_slider.get())
            tolerance = float(self.tol_entry.get().strip())
        except ValueError:
            messagebox.showerror("Invalid Parameters", "Similarity and tolerance must be valid numbers.")
            return

        self.is_scanning = True
        self.start_scan_btn.configure(state="disabled")
        self.progress_bar.set(0)
        self.status_label.configure(text=f"Scanning audio files in {directory}...")

        def run_scan():
            def progress_cb(current: int, total: int, filename: str, is_cached: bool):
                pct = current / total if total > 0 else 0
                status_str = "(Cached)" if is_cached else "(Fingerprinting)"
                self.after(0, lambda: self._update_scan_progress(pct, f"[{current}/{total}] {status_str} {filename[:40]}"))

            try:
                scan_stats = scan_directory(directory, self.db, progress_callback=progress_cb)
                dup_groups = find_and_rank_duplicates(self.db, similarity_threshold=similarity, duration_tolerance=tolerance)
            except Exception as e:
                err = str(e)
                self.after(0, lambda: self._on_scan_failed(err))
                return

            self.after(0, lambda: self._on_scan_completed(scan_stats, dup_groups))

        threading.Thread(target=run_scan, daemon=True).start()

    def _on_scan_failed(self, error: str):
        self.is_scanning = False
        self.start_scan_btn.configure(state="normal")
        self.status_label.configure(text=f"Scan failed: {error}")
        messagebox.showerror("Scan Failed", f"The scan stopped because of an error:\n\n{error}")

    def _update_scan_progress(self, progress_pct: float, status_text: str):
        self.progress_bar.set(progress_pct)
        self.status_label.configure(text=status_text)

    def _on_scan_completed(self, stats: Dict[str, Any], dup_groups: List[Dict[str, Any]]):
        self.is_scanning = False
        self.start_scan_btn.configure(state="normal")
        self.progress_bar.set(1.0)
        self.status_label.configure(
            text=f"Scan Complete! Scanned {stats['total_files']} tracks. Found {len(dup_groups)} duplicate group(s)."
        )

        self.duplicate_groups = dup_groups
        self.current_page = 1
        self.refresh_duplicates_view()
        self.refresh_stats_view()

    # -------------------------------------------------------------------------
    # Render Duplicate Groups (with Granular Checkboxes & Preview Buttons)
    # -------------------------------------------------------------------------
    def refresh_duplicates_view(self):
        # Clear existing widgets
        for widget in self.clusters_scroll.winfo_children():
            widget.destroy()

        self.candidate_checkboxes.clear()
        self.candidate_file_map.clear()

        # If duplicate_groups is empty, attempt fetching from DB
        if not self.duplicate_groups:
            try:
                sim = float(self.sim_slider.get())
                tol = float(self.tol_entry.get().strip())
                self.duplicate_groups = find_and_rank_duplicates(self.db, similarity_threshold=sim, duration_tolerance=tol)
            except Exception:
                self.duplicate_groups = []

        if not self.duplicate_groups:
            no_dup_lbl = ctk.CTkLabel(
                self.clusters_scroll,
                text="✨ No acoustic duplicates found in the library database!",
                font=ctk.CTkFont(size=14, weight="normal")
            )
            no_dup_lbl.pack(padx=20, pady=30)
            self.results_summary_label.configure(text="Acoustic Duplicate Clusters (0 Groups)")
            self.page_label.configure(text="Page 1 of 1")
            self.prev_page_btn.configure(state="disabled")
            self.next_page_btn.configure(state="disabled")
            return

        total_savings = sum(g["wasted_size"] for g in self.duplicate_groups)
        total_groups_count = len(self.duplicate_groups)
        max_page = max(1, (total_groups_count + self.page_size - 1) // self.page_size)
        self.current_page = min(self.current_page, max_page)

        start_idx = (self.current_page - 1) * self.page_size
        end_idx = start_idx + self.page_size
        page_groups = self.duplicate_groups[start_idx:end_idx]

        self.page_label.configure(text=f"Page {self.current_page} of {max_page} ({total_groups_count} Groups Total)")
        self.prev_page_btn.configure(state="normal" if self.current_page > 1 else "disabled")
        self.next_page_btn.configure(state="normal" if self.current_page < max_page else "disabled")

        self.results_summary_label.configure(
            text=f"Acoustic Duplicate Clusters ({total_groups_count} Groups | Reclaimable: {format_bytes(total_savings)})"
        )

        for relative_idx, group in enumerate(page_groups, 1):
            idx = start_idx + relative_idx
            master = group["master_file"]
            all_files = group["all_files"]
            wasted = format_bytes(group["wasted_size"])
            track_title = master.get("title") or os.path.basename(master["filepath"])
            artist_str = f" by {master['artist']}" if master.get("artist") else ""

            # Card container for group
            card = ctk.CTkFrame(self.clusters_scroll, corner_radius=8, border_width=1, border_color="gray35")
            card.pack(fill="x", padx=5, pady=8, expand=True)

            header = ctk.CTkLabel(
                card,
                text=f"Group #{idx}: {track_title}{artist_str} (Potential Savings: {wasted})",
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w"
            )
            header.pack(fill="x", padx=12, pady=(8, 4))

            for file_info in all_files:
                file_id = file_info["id"]
                rank = file_info["rank"]
                filepath = file_info["filepath"]
                badge = file_info["quality_badge"]
                size_str = format_bytes(file_info["filesize"])
                dur_str = f"{file_info['duration']:.1f}s" if file_info["duration"] > 0 else ""
                is_quarantined = file_info.get("is_quarantined", 0)

                row_frame = ctk.CTkFrame(card, fg_color="transparent")
                row_frame.pack(fill="x", padx=10, pady=4)

                if rank == 1:
                    rank_lbl = ctk.CTkLabel(
                        row_frame, text="✓ KEEP (Master)", text_color="#4CAF50", font=ctk.CTkFont(weight="bold"), width=120, anchor="w"
                    )
                    rank_lbl.pack(side="left", padx=5)
                else:
                    self.candidate_file_map[file_id] = file_info
                    cb = ctk.CTkCheckBox(row_frame, text="QUARANTINE", font=ctk.CTkFont(weight="bold"), width=120)
                    if not is_quarantined:
                        cb.select()  # Pre-check non-quarantined lower-quality duplicates
                    else:
                        cb.configure(text="QUARANTINED", state="disabled")
                    cb.pack(side="left", padx=5)
                    self.candidate_checkboxes[file_id] = cb

                info_str = f"{badge} | {size_str} | {dur_str}\n{filepath}"
                info_lbl = ctk.CTkLabel(row_frame, text=info_str, anchor="w", justify="left")
                info_lbl.pack(side="left", padx=10, fill="x", expand=True)

                play_btn = ctk.CTkButton(
                    row_frame, text="▶ Preview", width=75, height=26,
                    command=lambda p=filepath: self.player.load_and_play(p)
                )
                play_btn.pack(side="right", padx=5)

    # -------------------------------------------------------------------------
    # Granular Quarantine Execution
    # -------------------------------------------------------------------------
    def _quarantine_selected_candidates(self):
        # Stop any active audio preview playback to release file locks on Windows
        self.player.stop()

        selected_ids = [
            file_id for file_id, cb in self.candidate_checkboxes.items()
            if cb.get() == 1 and cb.cget("state") != "disabled"
        ]

        if not selected_ids:
            messagebox.showinfo("Selection Required", "No candidate duplicate files selected for quarantine.")
            return

        scan_dir = self.dir_entry.get().strip() or os.path.dirname(self.candidate_file_map[selected_ids[0]]["filepath"])

        confirm = messagebox.askyesno(
            "Confirm Quarantine",
            f"Are you sure you want to quarantine {len(selected_ids)} selected duplicate file(s)?\n\n"
            "Files will be moved safely to the 'quarantine/' directory."
        )
        if not confirm:
            return

        # Perform targeted quarantine operation
        res = quarantine_duplicates(
            db=self.db,
            base_scan_dir=scan_dir,
            quarantine_dir="quarantine",
            dry_run=False,
            target_file_ids=selected_ids
        )

        msg = (
            f"Successfully staged {res['moved_files']} file(s) into quarantine.\n"
            f"Freed {format_bytes(res['total_space_saved'])} of storage in active folders."
        )
        if res.get("errors"):
            msg += f"\n\nWarnings/Errors ({len(res['errors'])}):\n" + "\n".join(res["errors"][:5])

        messagebox.showinfo("Quarantine Completed", msg)

        self.duplicate_groups = []
        self.refresh_duplicates_view()
        self.refresh_quarantine_view()
        self.refresh_stats_view()

    # -------------------------------------------------------------------------
    # TAB 2: Quarantine Manager View
    # -------------------------------------------------------------------------
    def _setup_quarantine_tab(self):
        q_toolbar = ctk.CTkFrame(self.tab_quarantine, corner_radius=0, fg_color="transparent")
        q_toolbar.pack(side="top", fill="x", padx=10, pady=10)

        title_lbl = ctk.CTkLabel(q_toolbar, text="Quarantined Files Staging Area", font=ctk.CTkFont(size=16, weight="bold"))
        title_lbl.pack(side="left", padx=5)

        q_sel_all = ctk.CTkButton(q_toolbar, text="Select All", width=90, command=self._select_all_quarantined)
        q_sel_all.pack(side="left", padx=5)

        q_desel_all = ctk.CTkButton(q_toolbar, text="Deselect All", width=90, fg_color="gray50", hover_color="gray40", command=self._deselect_all_quarantined)
        q_desel_all.pack(side="left", padx=5)

        restore_btn = ctk.CTkButton(
            q_toolbar, text="↩ Restore Selected Files", width=170, fg_color="#2FA572", hover_color="#1E7852",
            command=self._restore_selected_quarantined
        )
        restore_btn.pack(side="right", padx=5)

        self.quarantine_scroll = ctk.CTkScrollableFrame(self.tab_quarantine, label_text="Active Quarantined Files")
        self.quarantine_scroll.pack(side="top", fill="both", expand=True, padx=10, pady=5)

    def _select_all_quarantined(self):
        for cb in self.quarantine_checkboxes.values():
            cb.select()

    def _deselect_all_quarantined(self):
        for cb in self.quarantine_checkboxes.values():
            cb.deselect()

    def refresh_quarantine_view(self):
        for widget in self.quarantine_scroll.winfo_children():
            widget.destroy()

        self.quarantine_checkboxes.clear()
        self.quarantined_file_map.clear()

        res = restore_quarantined_files(self.db, dry_run=True)
        plan = res.get("plan", [])

        if not plan:
            lbl = ctk.CTkLabel(
                self.quarantine_scroll, text="No active quarantined files found in database.",
                font=ctk.CTkFont(size=14)
            )
            lbl.pack(padx=20, pady=30)
            return

        for item in plan:
            file_id = item["file_id"]
            self.quarantined_file_map[file_id] = item

            card = ctk.CTkFrame(self.quarantine_scroll, corner_radius=6, border_width=1, border_color="gray35")
            card.pack(fill="x", padx=5, pady=5)

            cb = ctk.CTkCheckBox(card, text=f"File #{file_id}: {item['title']}", font=ctk.CTkFont(weight="bold"))
            cb.select()
            cb.pack(side="top", anchor="w", padx=10, pady=(8, 4))
            self.quarantine_checkboxes[file_id] = cb

            detail_str = f"Quarantined At: {item['quarantine_path']}\nOriginal Location: {item['original_path']}"
            detail_lbl = ctk.CTkLabel(card, text=detail_str, justify="left", anchor="w", text_color="gray70")
            detail_lbl.pack(side="left", padx=10, pady=(0, 8), fill="x", expand=True)

            play_btn = ctk.CTkButton(
                card, text="▶ Preview", width=75, height=26,
                command=lambda p=item['quarantine_path']: self.player.load_and_play(p)
            )
            play_btn.pack(side="right", padx=10, pady=(0, 8))

    def _restore_selected_quarantined(self):
        # Stop any active audio preview playback to release file locks on Windows
        self.player.stop()

        selected_ids = [
            file_id for file_id, cb in self.quarantine_checkboxes.items() if cb.get() == 1
        ]

        if not selected_ids:
            messagebox.showinfo("Selection Required", "No quarantined files selected to restore.")
            return

        confirm = messagebox.askyesno(
            "Confirm Restore",
            f"Are you sure you want to restore {len(selected_ids)} selected file(s) back to their original locations?"
        )
        if not confirm:
            return

        res = restore_quarantined_files(self.db, dry_run=False, target_file_ids=selected_ids)

        msg = f"Successfully restored {res['restored_files']} file(s)."
        if res.get("errors"):
            msg += f"\n\nWarnings/Errors ({len(res['errors'])}):\n" + "\n".join(res["errors"][:5])

        messagebox.showinfo("Restore Completed", msg)
        self.duplicate_groups = []
        self.refresh_duplicates_view()
        self.refresh_quarantine_view()
        self.refresh_stats_view()

    # -------------------------------------------------------------------------
    # TAB 3: Statistics Dashboard View
    # -------------------------------------------------------------------------
    def _setup_stats_tab(self):
        self.stats_container = ctk.CTkFrame(self.tab_stats, corner_radius=8)
        self.stats_container.pack(fill="both", expand=True, padx=20, pady=20)

    def refresh_stats_view(self):
        for widget in self.stats_container.winfo_children():
            widget.destroy()

        stats = self.db.get_stats()

        title_lbl = ctk.CTkLabel(
            self.stats_container, text="📊 Music Library & Database Overview", font=ctk.CTkFont(size=18, weight="bold")
        )
        title_lbl.pack(side="top", anchor="w", padx=20, pady=15)

        cards_frame = ctk.CTkFrame(self.stats_container, fg_color="transparent")
        cards_frame.pack(side="top", fill="x", padx=20, pady=10)

        # Helper card renderer
        def make_card(parent, title, val, color):
            f = ctk.CTkFrame(parent, corner_radius=8, fg_color=color)
            f.pack(side="left", fill="both", expand=True, padx=8, pady=5)
            t = ctk.CTkLabel(f, text=title, font=ctk.CTkFont(size=12), text_color="white")
            t.pack(padx=10, pady=(10, 2))
            v = ctk.CTkLabel(f, text=val, font=ctk.CTkFont(size=20, weight="bold"), text_color="white")
            v.pack(padx=10, pady=(2, 10))

        make_card(cards_frame, "Total Songs Scanned", str(stats["total_files"]), "#1E88E5")
        make_card(cards_frame, "Total Library Size", format_bytes(stats["total_size"]), "#8E24AA")
        make_card(cards_frame, "Duplicate Clusters", str(stats["duplicate_groups"]), "#FB8C00")
        make_card(cards_frame, "Reclaimable Storage", format_bytes(stats["wasted_space"]), "#D81B60")
        make_card(cards_frame, "Quarantined Files", str(stats["quarantined_count"]), "#43A047")

        # Database path & reset section
        db_info_frame = ctk.CTkFrame(self.stats_container, corner_radius=6)
        db_info_frame.pack(side="top", fill="x", padx=20, pady=20)

        db_lbl = ctk.CTkLabel(
            db_info_frame, text=f"Database Cache Location: {stats['db_path']}", font=ctk.CTkFont(size=12, slant="italic")
        )
        db_lbl.pack(side="left", padx=15, pady=15)

        reset_btn = ctk.CTkButton(
            db_info_frame, text="⚠ Clear Database Cache", fg_color="#D32F2F", hover_color="#9A0007", width=160,
            command=self._reset_database_cache
        )
        reset_btn.pack(side="right", padx=15, pady=15)

    def _reset_database_cache(self):
        confirm = messagebox.askyesno(
            "Clear Database Cache",
            "Are you sure you want to clear all cached metadata and fingerprint records from the database?"
        )
        if confirm:
            self.db.reset_db()
            messagebox.showinfo("Cache Cleared", "Database reset successfully.")
            self.duplicate_groups = []
            self.refresh_duplicates_view()
            self.refresh_quarantine_view()
            self.refresh_stats_view()


def main():
    app = MusicDupApp()
    app.mainloop()


if __name__ == "__main__":
    main()
