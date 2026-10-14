"""
Video Downloader (TikTok + YouTube)
-----------------------------------
Requirements:
    python -m pip install -U "yt-dlp[default,curl-cffi]"

Optional but recommended (needed for 1080p+ and MP3):
    ffmpeg  ->  https://ffmpeg.org/download.html
                (Windows: winget install ffmpeg | Mac: brew install ffmpeg
                 Linux: sudo apt install ffmpeg)

Run:
    python video_downloader.py
"""

import os
import shutil
import threading
import tkinter as tk
from concurrent.futures import ThreadPoolExecutor
from tkinter import ttk, filedialog, messagebox

try:
    import yt_dlp
except ImportError:
    raise SystemExit("yt-dlp is not installed. Run: python -m pip install -U yt-dlp")

SUPPORTED = ("tiktok.com", "youtube.com", "youtu.be")
HAS_FFMPEG = shutil.which("ffmpeg") is not None

QUALITY_OPTIONS = {
    "Best video": "bestvideo*+bestaudio/best",
    "1080p": "bestvideo[height<=1080]+bestaudio/best[height<=1080]",
    "720p": "bestvideo[height<=720]+bestaudio/best[height<=720]",
    "480p": "bestvideo[height<=480]+bestaudio/best[height<=480]",
    "Audio only (MP3)": "bestaudio/best",
}
SIMPLE_FORMAT = "best[ext=mp4]/best"  # single file, no ffmpeg needed


def site_of(url):
    if "tiktok.com" in url:
        return "TikTok"
    if "youtube.com" in url or "youtu.be" in url:
        return "YouTube"
    return "?"


class VideoDownloader(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Downloader - TikTok + YouTube")
        self.geometry("760x600")
        self.minsize(680, 540)

        self.folder_var = tk.StringVar(value=os.path.join(os.path.expanduser("~"), "Downloads"))
        self.workers_var = tk.IntVar(value=3)
        self.quality_var = tk.StringVar(value="Best video")
        self.cookie_browser_var = tk.StringVar(value="None")
        self.cookie_file_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Paste TikTok or YouTube links (one per line), then click Download All.")
        self.rows = {}
        self.done_count = 0
        self.failed = 0
        self.total = 0
        self.lock = threading.Lock()

        self._build_ui()

    # ---------- UI ----------
    def _build_ui(self):
        pad = {"padx": 12, "pady": 5}

        top = ttk.Frame(self)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Links (TikTok / YouTube, one per line):").pack(side="left")
        ttk.Button(top, text="Clear", command=self.clear_links).pack(side="right")
        ttk.Button(top, text="Paste", command=self.paste_links).pack(side="right", padx=6)

        box = ttk.Frame(self)
        box.pack(fill="x", **pad)
        self.text = tk.Text(box, height=8, wrap="none")
        sb = ttk.Scrollbar(box, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        self.text.pack(side="left", fill="x", expand=True)
        sb.pack(side="right", fill="y")

        folder = ttk.Frame(self)
        folder.pack(fill="x", **pad)
        ttk.Label(folder, text="Save to:").pack(side="left")
        ttk.Entry(folder, textvariable=self.folder_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(folder, text="Browse...", command=self.choose_folder).pack(side="left")

        opts = ttk.Frame(self)
        opts.pack(fill="x", **pad)
        ttk.Label(opts, text="Quality:").pack(side="left")
        ttk.Combobox(opts, textvariable=self.quality_var, values=list(QUALITY_OPTIONS),
                     state="readonly", width=16).pack(side="left", padx=6)
        ttk.Label(opts, text="At once:").pack(side="left", padx=(12, 0))
        ttk.Spinbox(opts, from_=1, to=8, width=4, textvariable=self.workers_var).pack(side="left", padx=6)
        self.download_btn = ttk.Button(opts, text="Download All", command=self.start_download)
        self.download_btn.pack(side="right", ipadx=20, ipady=3)

        cookies = ttk.Frame(self)
        cookies.pack(fill="x", **pad)
        ttk.Label(cookies, text="Cookies from browser:").pack(side="left")
        ttk.Combobox(cookies, textvariable=self.cookie_browser_var, state="readonly", width=10,
                     values=["None", "firefox", "chrome", "edge", "brave", "opera", "safari"]).pack(side="left", padx=6)
        ttk.Label(cookies, text="or cookies.txt:").pack(side="left", padx=(12, 0))
        ttk.Entry(cookies, textvariable=self.cookie_file_var, width=22).pack(side="left", padx=6)
        ttk.Button(cookies, text="Browse...", command=self.choose_cookie_file).pack(side="left")

        if not HAS_FFMPEG:
            ttk.Label(self, foreground="#b45309",
                      text="ffmpeg not found: downloads will use a single-file format (up to 720p on YouTube); MP3 is disabled.",
                      wraplength=720).pack(**pad)

        cols = ("site", "link", "status")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=8)
        self.tree.heading("site", text="Site")
        self.tree.heading("link", text="Link")
        self.tree.heading("status", text="Status")
        self.tree.column("site", width=70, anchor="center")
        self.tree.column("link", width=430)
        self.tree.column("status", width=190, anchor="center")
        self.tree.pack(fill="both", expand=True, **pad)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", **pad)
        ttk.Label(self, textvariable=self.status_var).pack(**pad)

    # ---------- Helpers ----------
    def paste_links(self):
        try:
            clip = self.clipboard_get().strip()
        except tk.TclError:
            messagebox.showwarning("Clipboard empty", "There is nothing to paste.")
            return
        current = self.text.get("1.0", "end").strip()
        self.text.insert("end", ("\n" if current else "") + clip)

    def clear_links(self):
        self.text.delete("1.0", "end")

    def choose_folder(self):
        folder = filedialog.askdirectory(initialdir=self.folder_var.get())
        if folder:
            self.folder_var.set(folder)

    def choose_cookie_file(self):
        path = filedialog.askopenfilename(title="Select cookies.txt",
                                          filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if path:
            self.cookie_file_var.set(path)

    def set_status(self, url, text):
        self.after(0, lambda: self.tree.set(self.rows[url], "status", text))

    # ---------- Downloading ----------
    def start_download(self):
        folder = self.folder_var.get().strip()
        if not os.path.isdir(folder):
            messagebox.showerror("Invalid folder", "Please choose a valid save location.")
            return

        quality = self.quality_var.get()
        if quality == "Audio only (MP3)" and not HAS_FFMPEG:
            messagebox.showerror("ffmpeg required", "MP3 conversion needs ffmpeg installed.\nChoose a video quality or install ffmpeg.")
            return

        raw = [ln.strip() for ln in self.text.get("1.0", "end").splitlines()]
        urls = list(dict.fromkeys(u for u in raw if any(s in u for s in SUPPORTED)))
        if not urls:
            messagebox.showerror("No links", "Please paste at least one TikTok or YouTube link.")
            return

        self.tree.delete(*self.tree.get_children())
        self.rows = {u: self.tree.insert("", "end", values=(site_of(u), u, "Waiting...")) for u in urls}
        self.total = len(urls)
        self.done_count = 0
        self.failed = 0
        self.progress.configure(maximum=self.total, value=0)
        self.status_var.set(f"Downloading 0 / {self.total}...")
        self.download_btn.config(state="disabled")

        workers = max(1, min(8, int(self.workers_var.get())))
        threading.Thread(target=self._run_all, args=(urls, folder, workers, quality), daemon=True).start()

    def _run_all(self, urls, folder, workers, quality):
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for url in urls:
                pool.submit(self._download_one, url, folder, quality)
        self.after(0, self._finish)

    def _build_opts(self, url, folder, quality, hook):
        opts = {
            "outtmpl": os.path.join(folder, "%(uploader)s - %(title).80s [%(id)s].%(ext)s"),
            "noplaylist": True,          # only the single video, not whole playlists
            "quiet": True,
            "no_warnings": True,
            "progress_hooks": [hook],
        }

        if HAS_FFMPEG:
            opts["format"] = QUALITY_OPTIONS[quality]
            if quality == "Audio only (MP3)":
                opts["postprocessors"] = [{
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": "mp3",
                    "preferredquality": "192",
                }]
            else:
                opts["merge_output_format"] = "mp4"
        else:
            opts["format"] = SIMPLE_FORMAT

        # Browser impersonation helps with TikTok blocks
        if site_of(url) == "TikTok":
            try:
                from yt_dlp.networking.impersonate import ImpersonateTarget
                opts["impersonate"] = ImpersonateTarget("chrome")
            except Exception:
                pass

        # Cookies (needed when YouTube says "Sign in to confirm you're not a bot")
        cookie_file = self.cookie_file_var.get().strip()
        browser = self.cookie_browser_var.get().strip()
        if cookie_file and os.path.isfile(cookie_file):
            opts["cookiefile"] = cookie_file
        elif browser and browser != "None":
            opts["cookiesfrombrowser"] = (browser,)
        return opts

    def _download_one(self, url, folder, quality):
        def hook(d):
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if total:
                    self.set_status(url, f"Downloading {d['downloaded_bytes'] / total * 100:.0f}%")
            elif d["status"] == "finished":
                self.set_status(url, "Processing...")

        self.set_status(url, "Starting...")
        try:
            with yt_dlp.YoutubeDL(self._build_opts(url, folder, quality, hook)) as ydl:
                ydl.download([url])
            self.set_status(url, "Done")
        except Exception as e:
            with self.lock:
                self.failed += 1
            msg = str(e).replace("ERROR: ", "")
            self.set_status(url, "Failed: " + msg[:40])
        finally:
            with self.lock:
                self.done_count += 1
                n = self.done_count
            self.after(0, lambda: self._update_overall(n))

    def _update_overall(self, n):
        self.progress["value"] = n
        self.status_var.set(f"Downloading {n} / {self.total}...")

    def _finish(self):
        self.download_btn.config(state="normal")
        ok = self.total - self.failed
        self.status_var.set(f"Finished: {ok} succeeded, {self.failed} failed.")
        messagebox.showinfo("Finished", f"{ok} succeeded, {self.failed} failed.\n\nSaved to:\n{self.folder_var.get()}")


if __name__ == "__main__":
    VideoDownloader().mainloop()