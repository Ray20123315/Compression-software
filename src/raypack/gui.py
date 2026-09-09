from __future__ import annotations

import queue
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __author__, __version__
from .core import compress_archive, extract_archive, list_archive, verify_archive

PROFILE_LABELS = {
    "AutoBest（最小優先）": "autobest",
    "Ultra（LZMA2 高壓縮）": "ultra",
    "Minecraft（MC 整合包）": "minecraft",
    "Balanced（平衡）": "balanced",
    "Fast（Zstd 快速）": "fast",
}
FORMAT_LABELS = {"RAYZ（推薦）": "rayz", "ZIP（高相容）": "zip", "TAR.XZ（Unix 相容）": "tar.xz"}


def _human_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if size < 1024 or unit == "TiB":
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} B"


class RayPackApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"RayPack {__version__} — ray20123315")
        self.geometry("960x680")
        self.minsize(820, 600)
        self.queue: queue.Queue[tuple[str, object]] = queue.Queue()
        self.inputs: list[str] = []
        self._build_style()
        self._build_ui()
        self.after(120, self._pump_queue)

    def _build_style(self) -> None:
        style = ttk.Style(self)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 20, "bold"))
        style.configure("Sub.TLabel", font=("Segoe UI", 10))
        style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"), padding=(12, 8))
        style.configure("TNotebook.Tab", padding=(14, 8))
        style.configure("Treeview", rowheight=25)

    def _build_ui(self) -> None:
        header = ttk.Frame(self, padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="RayPack", style="Title.TLabel").pack(side="left")
        ttk.Label(header, text="  高壓縮・無損封存工具", style="Sub.TLabel").pack(side="left", pady=(8, 0))
        ttk.Label(header, text=f"作者：{__author__}", style="Sub.TLabel").pack(side="right", pady=(8, 0))
        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self.compress_tab = ttk.Frame(notebook, padding=14)
        self.extract_tab = ttk.Frame(notebook, padding=14)
        self.about_tab = ttk.Frame(notebook, padding=20)
        notebook.add(self.compress_tab, text="壓縮")
        notebook.add(self.extract_tab, text="解壓 / 檢查")
        notebook.add(self.about_tab, text="關於")
        self._build_compress_tab()
        self._build_extract_tab()
        self._build_about_tab()

    def _build_compress_tab(self) -> None:
        left = ttk.Frame(self.compress_tab)
        left.pack(fill="both", expand=True)
        ttk.Label(left, text="1. 選擇要壓縮的檔案與資料夾").pack(anchor="w")
        list_frame = ttk.Frame(left)
        list_frame.pack(fill="both", expand=True, pady=(6, 10))
        self.input_list = tk.Listbox(list_frame, selectmode="extended", font=("Segoe UI", 10))
        self.input_list.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(list_frame, orient="vertical", command=self.input_list.yview)
        sb.pack(side="right", fill="y")
        self.input_list.configure(yscrollcommand=sb.set)
        buttons = ttk.Frame(left)
        buttons.pack(fill="x", pady=(0, 12))
        ttk.Button(buttons, text="加入檔案", command=self._add_files).pack(side="left")
        ttk.Button(buttons, text="加入資料夾", command=self._add_folder).pack(side="left", padx=6)
        ttk.Button(buttons, text="移除選取", command=self._remove_selected).pack(side="left")
        ttk.Button(buttons, text="清空", command=self._clear_inputs).pack(side="left", padx=6)
        grid = ttk.Frame(left)
        grid.pack(fill="x")
        grid.columnconfigure(1, weight=1)
        ttk.Label(grid, text="2. 輸出：").grid(row=0, column=0, sticky="w", pady=5)
        self.output_var = tk.StringVar()
        ttk.Entry(grid, textvariable=self.output_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(grid, text="瀏覽", command=self._browse_output).grid(row=0, column=2)
        ttk.Label(grid, text="3. 格式：").grid(row=1, column=0, sticky="w", pady=5)
        self.format_var = tk.StringVar(value="RAYZ（推薦）")
        fmt_box = ttk.Combobox(grid, textvariable=self.format_var, state="readonly", values=list(FORMAT_LABELS), width=28)
        fmt_box.grid(row=1, column=1, sticky="w", padx=8)
        fmt_box.bind("<<ComboboxSelected>>", lambda _: self._ensure_output_extension())
        ttk.Label(grid, text="4. 模式：").grid(row=2, column=0, sticky="w", pady=5)
        self.profile_var = tk.StringVar(value="AutoBest（最小優先）")
        profile_box = ttk.Combobox(grid, textvariable=self.profile_var, state="readonly", values=list(PROFILE_LABELS), width=28)
        profile_box.grid(row=2, column=1, sticky="w", padx=8)
        profile_box.bind("<<ComboboxSelected>>", lambda _: self._update_profile_note())
        self.profile_note = ttk.Label(grid, wraplength=710, foreground="#555555")
        self.profile_note.grid(row=3, column=0, columnspan=3, sticky="w", pady=(6, 10))
        self._update_profile_note()
        action = ttk.Frame(left)
        action.pack(fill="x", pady=(2, 0))
        self.compress_button = ttk.Button(action, text="開始壓縮", style="Accent.TButton", command=self._start_compress)
        self.compress_button.pack(side="left")
        self.compress_progress = ttk.Progressbar(action, mode="determinate", maximum=100)
        self.compress_progress.pack(side="left", fill="x", expand=True, padx=(12, 0))
        self.compress_status = ttk.Label(left, text="就緒")
        self.compress_status.pack(anchor="w", pady=(8, 0))

    def _build_extract_tab(self) -> None:
        top = ttk.Frame(self.extract_tab)
        top.pack(fill="x")
        top.columnconfigure(1, weight=1)
        ttk.Label(top, text="封存檔：").grid(row=0, column=0, sticky="w")
        self.archive_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.archive_var).grid(row=0, column=1, sticky="ew", padx=8)
        ttk.Button(top, text="瀏覽", command=self._browse_archive).grid(row=0, column=2)
        ttk.Label(top, text="解壓到：").grid(row=1, column=0, sticky="w", pady=8)
        self.extract_dest_var = tk.StringVar()
        ttk.Entry(top, textvariable=self.extract_dest_var).grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(top, text="瀏覽", command=self._browse_extract_dest).grid(row=1, column=2)
        actions = ttk.Frame(self.extract_tab)
        actions.pack(fill="x", pady=(6, 10))
        ttk.Button(actions, text="讀取內容", command=self._inspect_archive).pack(side="left")
        ttk.Button(actions, text="驗證完整性", command=self._verify_archive).pack(side="left", padx=6)
        self.extract_button = ttk.Button(actions, text="開始解壓", style="Accent.TButton", command=self._start_extract)
        self.extract_button.pack(side="left")
        self.tree = ttk.Treeview(self.extract_tab, columns=("size", "type"), show="tree headings")
        self.tree.heading("#0", text="路徑")
        self.tree.heading("size", text="大小")
        self.tree.heading("type", text="類型")
        self.tree.column("#0", width=610)
        self.tree.column("size", width=120, anchor="e")
        self.tree.column("type", width=80, anchor="center")
        self.tree.pack(fill="both", expand=True)
        self.extract_progress = ttk.Progressbar(self.extract_tab, mode="determinate", maximum=100)
        self.extract_progress.pack(fill="x", pady=(10, 0))
        self.extract_status = ttk.Label(self.extract_tab, text="就緒")
        self.extract_status.pack(anchor="w", pady=(6, 0))

    def _build_about_tab(self) -> None:
        text = (f"RayPack {__version__}\n\n作者：{__author__}\nCopyright © 2026 ray20123315. All Rights Reserved.\n\nRayPack 是通用型無損封存工具。RAYZ 的 AutoBest 會比較高壓縮候選並選較小者；Minecraft 模式則將可壓縮設定/腳本資料優先放進 solid stream，再處理 JAR、圖片、影片、音訊等已壓縮資料。\n\n注意：任何無損壓縮器都不可能保證每種資料都比 7-Zip 小；JPG、PNG、MP4、MP3、JAR、ZIP 等格式通常已經壓縮。RayPack 不會為了追求較小數字而偷偷轉碼或降低品質。")
        ttk.Label(self.about_tab, text=text, wraplength=780, justify="left", font=("Segoe UI", 11)).pack(anchor="nw")

    def _add_files(self) -> None:
        self._append_inputs(filedialog.askopenfilenames(title="選擇檔案"))

    def _add_folder(self) -> None:
        path = filedialog.askdirectory(title="選擇資料夾")
        if path:
            self._append_inputs([path])

    def _append_inputs(self, paths) -> None:
        for p in paths:
            if p not in self.inputs:
                self.inputs.append(p)
                self.input_list.insert("end", p)
        if self.inputs and not self.output_var.get():
            base = Path(self.inputs[0])
            self.output_var.set(str(base.parent / f"{base.stem or base.name}.rayz"))

    def _remove_selected(self) -> None:
        for idx in reversed(list(self.input_list.curselection())):
            self.input_list.delete(idx)
            del self.inputs[idx]

    def _clear_inputs(self) -> None:
        self.inputs.clear()
        self.input_list.delete(0, "end")

    def _browse_output(self) -> None:
        fmt = FORMAT_LABELS[self.format_var.get()]
        ext = ".rayz" if fmt == "rayz" else ".zip" if fmt == "zip" else ".tar.xz"
        path = filedialog.asksaveasfilename(title="輸出封存檔", defaultextension=ext)
        if path:
            self.output_var.set(path)

    def _ensure_output_extension(self) -> None:
        current = self.output_var.get().strip()
        if not current:
            return
        fmt = FORMAT_LABELS[self.format_var.get()]
        ext = ".rayz" if fmt == "rayz" else ".zip" if fmt == "zip" else ".tar.xz"
        path = Path(current)
        lower = path.name.lower()
        for known in (".tar.xz", ".rayz", ".zip"):
            if lower.endswith(known):
                path = path.with_name(path.name[: -len(known)] + ext)
                break
        else:
            path = path.with_name(path.name + ext)
        self.output_var.set(str(path))

    def _update_profile_note(self) -> None:
        profile = PROFILE_LABELS[self.profile_var.get()]
        notes = {"autobest": "最小優先：同一份 solid TAR 會嘗試 LZMA2 與 Brotli q11，再選較小結果；速度最慢，也需要較多暫存空間。", "ultra": "高壓縮：使用 192 MiB LZMA2 dictionary，適合備份與長期保存。", "minecraft": "MC 整合包：先排序 JSON/TOML/CFG/腳本等高可壓縮資料，再放 JAR/ZIP/圖片/影音；不解包或改寫 Mod。", "balanced": "平衡：32 MiB LZMA2 dictionary，記憶體需求較低。", "fast": "快速：Zstd level 12，多執行緒；比 Ultra 快很多，但通常壓縮率較低。"}
        self.profile_note.configure(text=notes[profile])

    def _browse_archive(self) -> None:
        path = filedialog.askopenfilename(title="選擇封存檔", filetypes=[("支援格式", "*.rayz *.zip *.jar *.mrpack *.mcpack *.tar.xz *.txz *.tar.gz *.tgz *.tar"), ("所有檔案", "*.*")])
        if path:
            self.archive_var.set(path)
            p = Path(path)
            name = p.name
            for ext in (".tar.xz", ".tar.gz", ".rayz", ".zip", ".txz", ".tgz", ".tar"):
                if name.lower().endswith(ext):
                    name = name[: -len(ext)]
                    break
            self.extract_dest_var.set(str(p.parent / name))

    def _browse_extract_dest(self) -> None:
        path = filedialog.askdirectory(title="選擇解壓縮資料夾")
        if path:
            self.extract_dest_var.set(path)

    def _set_busy(self, busy: bool) -> None:
        self.compress_button.configure(state="disabled" if busy else "normal")
        self.extract_button.configure(state="disabled" if busy else "normal")

    def _run_worker(self, fn) -> None:
        self._set_busy(True)
        threading.Thread(target=self._worker_wrapper, args=(fn,), daemon=True).start()

    def _worker_wrapper(self, fn) -> None:
        try:
            self.queue.put(("success", fn()))
        except Exception as exc:
            self.queue.put(("error", exc))

    def _progress_callback(self, message: str, fraction: float | None) -> None:
        self.queue.put(("progress", (message, fraction)))

    def _start_compress(self) -> None:
        if not self.inputs:
            messagebox.showwarning("RayPack", "請先加入至少一個檔案或資料夾。")
            return
        output = self.output_var.get().strip()
        if not output:
            messagebox.showwarning("RayPack", "請指定輸出檔案。")
            return
        fmt = FORMAT_LABELS[self.format_var.get()]
        profile = PROFILE_LABELS[self.profile_var.get()]
        self.compress_progress["value"] = 0
        self.compress_status.configure(text="準備中…")
        self._run_worker(lambda: ("compress", compress_archive(self.inputs, output, format=fmt, profile=profile, progress=self._progress_callback)))

    def _start_extract(self) -> None:
        archive = self.archive_var.get().strip()
        dest = self.extract_dest_var.get().strip()
        if not archive or not dest:
            messagebox.showwarning("RayPack", "請選擇封存檔與輸出資料夾。")
            return
        self.extract_progress["value"] = 0
        self.extract_status.configure(text="準備中…")
        self._run_worker(lambda: ("extract", extract_archive(archive, dest, progress=self._progress_callback)))

    def _inspect_archive(self) -> None:
        archive = self.archive_var.get().strip()
        if archive:
            self.extract_status.configure(text="讀取內容…")
            self._run_worker(lambda: ("list", list_archive(archive)))

    def _verify_archive(self) -> None:
        archive = self.archive_var.get().strip()
        if archive:
            self.extract_status.configure(text="驗證中…")
            self._run_worker(lambda: ("verify", verify_archive(archive)))

    def _pump_queue(self) -> None:
        try:
            while True:
                kind, payload = self.queue.get_nowait()
                if kind == "progress":
                    message, fraction = payload
                    self.compress_status.configure(text=message)
                    self.extract_status.configure(text=message)
                    if fraction is not None:
                        self.compress_progress["value"] = fraction * 100
                        self.extract_progress["value"] = fraction * 100
                elif kind == "error":
                    self._set_busy(False)
                    self.compress_status.configure(text=f"失敗：{payload}")
                    self.extract_status.configure(text=f"失敗：{payload}")
                    messagebox.showerror("RayPack", str(payload))
                elif kind == "success":
                    self._set_busy(False)
                    action, result = payload
                    if action == "compress":
                        saving = 100 * (1 - result.ratio) if result.input_bytes else 0
                        msg = f"完成：{result.output.name} | {_human_size(result.output_bytes)} | 節省 {saving:.2f}% | {result.codec}"
                        self.compress_status.configure(text=msg)
                        self.compress_progress["value"] = 100
                        messagebox.showinfo("RayPack", msg)
                    elif action == "extract":
                        self.extract_progress["value"] = 100
                        self.extract_status.configure(text=f"解壓完成：{result}")
                        messagebox.showinfo("RayPack", f"解壓完成：\n{result}")
                    elif action == "list":
                        self.tree.delete(*self.tree.get_children())
                        for entry in result:
                            self.tree.insert("", "end", text=entry.name, values=(_human_size(entry.size), "資料夾" if entry.is_dir else "檔案"))
                        self.extract_status.configure(text=f"已讀取 {len(result)} 個項目")
                    elif action == "verify":
                        self.extract_status.configure(text="驗證通過" if result.get("ok") else "驗證失敗")
                        messagebox.showinfo("RayPack", "驗證通過。\n" + "\n".join(f"{k}: {v}" for k, v in result.items() if k != "ok"))
        except queue.Empty:
            pass
        self.after(120, self._pump_queue)


def main() -> None:
    RayPackApp().mainloop()


if __name__ == "__main__":
    main()
