from __future__ import annotations

import hashlib
import json
import lzma
import os
import shutil
import struct
import tarfile
import tempfile
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Sequence

import brotli

try:
    import zstandard as zstd
except ImportError:
    zstd = None

from . import __author__, __version__

ProgressCallback = Callable[[str, float | None], None]
MAGIC = b"RAYZ\x01"
HEADER_STRUCT = struct.Struct("<I")
BUFFER_SIZE = 1024 * 1024
COMPRESSED_EXTENSIONS = {".7z", ".aac", ".avi", ".avif", ".br", ".bz2", ".flac", ".gif", ".gz", ".jar", ".jpeg", ".jpg", ".lz4", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".opus", ".png", ".rar", ".webm", ".webp", ".xz", ".zip", ".zst"}
TEXT_EXTENSIONS = {".cfg", ".conf", ".css", ".csv", ".ini", ".java", ".js", ".json", ".kt", ".lang", ".lua", ".mcfunction", ".mcmeta", ".md", ".properties", ".py", ".toml", ".ts", ".txt", ".xml", ".yaml", ".yml"}


class RayPackError(Exception):
    """Base error for RayPack operations."""


class ArchiveSecurityError(RayPackError):
    """Raised when an archive contains an unsafe extraction path."""


@dataclass(frozen=True)
class ArchiveEntry:
    name: str
    size: int
    is_dir: bool


@dataclass(frozen=True)
class OperationResult:
    output: Path
    input_bytes: int
    output_bytes: int
    codec: str
    profile: str
    elapsed_seconds: float

    @property
    def ratio(self) -> float:
        return (self.output_bytes / self.input_bytes) if self.input_bytes else 0.0


def _notify(callback: ProgressCallback | None, message: str, fraction: float | None = None) -> None:
    if callback:
        callback(message, fraction)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(BUFFER_SIZE):
            h.update(chunk)
    return h.hexdigest()


def _safe_member_path(name: str) -> PurePosixPath:
    normalized = name.replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if candidate.is_absolute() or any(part in {"..", ""} for part in candidate.parts):
        raise ArchiveSecurityError(f"不安全的封存路徑：{name}")
    if candidate.parts and candidate.parts[0].endswith(":"):
        raise ArchiveSecurityError(f"不安全的磁碟機路徑：{name}")
    return candidate


def _safe_link_target(member_name: str, link_name: str) -> None:
    target = PurePosixPath(link_name.replace("\\", "/"))
    if target.is_absolute():
        raise ArchiveSecurityError(f"不安全的符號連結：{member_name} -> {link_name}")
    base = PurePosixPath(member_name).parent
    resolved_parts: list[str] = []
    for part in (base / target).parts:
        if part in ("", "."):
            continue
        if part == "..":
            if not resolved_parts:
                raise ArchiveSecurityError(f"符號連結超出輸出目錄：{member_name} -> {link_name}")
            resolved_parts.pop()
        else:
            resolved_parts.append(part)


def _validate_tar_members(tf: tarfile.TarFile) -> None:
    for member in tf.getmembers():
        _safe_member_path(member.name)
        if member.issym() or member.islnk():
            _safe_link_target(member.name, member.linkname)


def _safe_extract_tar(tf: tarfile.TarFile, destination: Path) -> None:
    _validate_tar_members(tf)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        tf.extractall(destination, filter="data")
    except TypeError:
        tf.extractall(destination)


def _safe_extract_zip(zf: zipfile.ZipFile, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    for info in zf.infolist():
        rel = _safe_member_path(info.filename)
        target = (destination / Path(*rel.parts)).resolve()
        if os.path.commonpath([str(root), str(target)]) != str(root):
            raise ArchiveSecurityError(f"ZIP 項目超出輸出目錄：{info.filename}")
    zf.extractall(destination)


def _flatten_inputs(inputs: Sequence[Path], minecraft_order: bool = False) -> list[tuple[Path, str]]:
    if not inputs:
        raise RayPackError("至少需要一個輸入檔案或資料夾。")
    top_names: set[str] = set()
    entries: list[tuple[Path, str]] = []
    for source in inputs:
        source = source.expanduser().resolve()
        if not source.exists() and not source.is_symlink():
            raise FileNotFoundError(str(source))
        top = source.name or source.anchor.replace(":", "") or "root"
        if top in top_names:
            raise RayPackError(f"輸入頂層名稱重複：{top}")
        top_names.add(top)
        if source.is_dir() and not source.is_symlink():
            entries.append((source, top))
            for child in source.rglob("*"):
                rel = child.relative_to(source).as_posix()
                entries.append((child, f"{top}/{rel}"))
        else:
            entries.append((source, top))

    def sort_key(item: tuple[Path, str]) -> tuple[int, int, str]:
        path, arcname = item
        if path.is_dir() and not path.is_symlink():
            return (0, arcname.count("/"), arcname.lower())
        if not minecraft_order:
            return (1, arcname.count("/"), arcname.lower())
        ext = path.suffix.lower()
        if ext in TEXT_EXTENSIONS:
            rank = 1
        elif ext in COMPRESSED_EXTENSIONS:
            rank = 3
        else:
            rank = 2
        return (rank, arcname.count("/"), arcname.lower())

    return sorted(entries, key=sort_key)


def _input_size(entries: Sequence[tuple[Path, str]]) -> int:
    total = 0
    seen: set[tuple[int, int]] = set()
    for path, _ in entries:
        try:
            st = path.stat(follow_symlinks=False)
        except (FileNotFoundError, OSError):
            continue
        if path.is_file() and not path.is_symlink():
            key = (getattr(st, "st_dev", 0), getattr(st, "st_ino", id(path)))
            if key not in seen:
                seen.add(key)
                total += st.st_size
    return total


def _create_tar(entries: Sequence[tuple[Path, str]], tar_path: Path, progress: ProgressCallback | None) -> None:
    _notify(progress, "建立 solid 封裝資料流…", 0.05)
    total = max(len(entries), 1)
    with tarfile.open(tar_path, mode="w", format=tarfile.PAX_FORMAT, dereference=False) as tf:
        for index, (path, arcname) in enumerate(entries, start=1):
            tf.add(path, arcname=arcname, recursive=False)
            if index % 50 == 0 or index == total:
                _notify(progress, f"封裝 {index}/{total} 個項目…", 0.05 + (index / total) * 0.20)


def _lzma_filters(profile: str) -> list[dict[str, int]]:
    if profile == "balanced":
        dict_size = 32 * 1024 * 1024
        nice_len = 128
    elif profile == "minecraft":
        dict_size = 128 * 1024 * 1024
        nice_len = 273
    else:
        dict_size = 192 * 1024 * 1024
        nice_len = 273
    return [{"id": lzma.FILTER_LZMA2, "dict_size": dict_size, "lc": 3, "lp": 0, "pb": 2, "mode": lzma.MODE_NORMAL, "nice_len": nice_len, "mf": lzma.MF_BT4, "depth": 0}]


def _compress_lzma(tar_path: Path, out_path: Path, profile: str, progress: ProgressCallback | None) -> None:
    _notify(progress, "LZMA2 高壓縮中…", 0.35)
    with tar_path.open("rb") as src, lzma.open(out_path, "wb", format=lzma.FORMAT_XZ, check=lzma.CHECK_CRC64, filters=_lzma_filters(profile)) as dst:
        while chunk := src.read(BUFFER_SIZE):
            dst.write(chunk)


def _compress_brotli(tar_path: Path, out_path: Path, progress: ProgressCallback | None) -> None:
    _notify(progress, "Brotli q11 候選壓縮中…", 0.55)
    compressor = brotli.Compressor(mode=brotli.MODE_GENERIC, quality=11, lgwin=24)
    with tar_path.open("rb") as src, out_path.open("wb") as dst:
        while chunk := src.read(BUFFER_SIZE):
            part = compressor.process(chunk)
            if part:
                dst.write(part)
        dst.write(compressor.finish())


def _compress_zstd(tar_path: Path, out_path: Path, progress: ProgressCallback | None) -> None:
    if zstd is None:
        raise RayPackError("Fast Zstd 需要 zstandard 套件；正式 Windows 版已內建。")
    _notify(progress, "Zstd 快速壓縮中…", 0.40)
    compressor = zstd.ZstdCompressor(level=12, threads=-1, write_checksum=True)
    with tar_path.open("rb") as src, out_path.open("wb") as raw:
        with compressor.stream_writer(raw, closefd=False) as dst:
            shutil.copyfileobj(src, dst, BUFFER_SIZE)


def _write_rayz(output: Path, payload: Path, metadata: dict[str, object]) -> None:
    encoded = json.dumps(metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    if len(encoded) > 1024 * 1024:
        raise RayPackError("RAYZ metadata 過大。")
    temp = output.with_suffix(output.suffix + ".tmp")
    with temp.open("wb") as dst, payload.open("rb") as src:
        dst.write(MAGIC)
        dst.write(HEADER_STRUCT.pack(len(encoded)))
        dst.write(encoded)
        shutil.copyfileobj(src, dst, BUFFER_SIZE)
    os.replace(temp, output)


def _read_rayz_header(path: Path) -> tuple[dict[str, object], int]:
    with path.open("rb") as fh:
        magic = fh.read(len(MAGIC))
        if magic != MAGIC:
            raise RayPackError("不是有效的 RAYZ 檔案或格式版本不支援。")
        raw_len = fh.read(HEADER_STRUCT.size)
        if len(raw_len) != HEADER_STRUCT.size:
            raise RayPackError("RAYZ 標頭損毀。")
        (meta_len,) = HEADER_STRUCT.unpack(raw_len)
        if meta_len <= 0 or meta_len > 1024 * 1024:
            raise RayPackError("RAYZ metadata 長度異常。")
        meta_raw = fh.read(meta_len)
        if len(meta_raw) != meta_len:
            raise RayPackError("RAYZ metadata 不完整。")
        try:
            meta = json.loads(meta_raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RayPackError("RAYZ metadata 無法解析。") from exc
        return meta, len(MAGIC) + HEADER_STRUCT.size + meta_len


def _decompress_rayz_to_tar(path: Path, tar_path: Path, progress: ProgressCallback | None = None) -> dict[str, object]:
    meta, offset = _read_rayz_header(path)
    codec = str(meta.get("codec", ""))
    _notify(progress, f"解碼 {codec} 資料流…", 0.20)
    with path.open("rb") as raw:
        raw.seek(offset)
        if codec == "lzma2-xz":
            with lzma.LZMAFile(raw, "rb") as src, tar_path.open("wb") as dst:
                shutil.copyfileobj(src, dst, BUFFER_SIZE)
        elif codec == "brotli":
            decompressor = brotli.Decompressor()
            with tar_path.open("wb") as dst:
                while chunk := raw.read(BUFFER_SIZE):
                    part = decompressor.process(chunk)
                    if part:
                        dst.write(part)
                if not decompressor.is_finished():
                    raise RayPackError("Brotli 資料流不完整。")
        elif codec == "zstd":
            if zstd is None:
                raise RayPackError("此 RAYZ 使用 Zstd；目前環境缺少 zstandard 套件。")
            with zstd.ZstdDecompressor().stream_reader(raw) as src, tar_path.open("wb") as dst:
                shutil.copyfileobj(src, dst, BUFFER_SIZE)
        else:
            raise RayPackError(f"不支援的 RAYZ codec：{codec}")
    expected = meta.get("tar_sha256")
    if expected and _sha256_file(tar_path) != expected:
        raise RayPackError("RAYZ 完整性驗證失敗：payload SHA-256 不符。")
    return meta


def compress_archive(inputs: Sequence[str | os.PathLike[str]], output: str | os.PathLike[str], *, format: str = "rayz", profile: str = "autobest", progress: ProgressCallback | None = None) -> OperationResult:
    start = time.monotonic()
    output_path = Path(output).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fmt = format.lower().replace(".", "")
    profile = profile.lower()
    if profile not in {"autobest", "ultra", "balanced", "fast", "minecraft"}:
        raise RayPackError(f"未知壓縮模式：{profile}")
    entries = _flatten_inputs([Path(p) for p in inputs], minecraft_order=(profile == "minecraft"))
    if any(path.resolve() == output_path for path, _ in entries if path.exists()):
        raise RayPackError("輸出檔案不能同時是輸入檔案。")
    input_bytes = _input_size(entries)

    if fmt == "zip":
        _notify(progress, "建立 ZIP…", 0.15)
        temp = output_path.with_suffix(output_path.suffix + ".tmp")
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as zf:
            for i, (path, arcname) in enumerate(entries, 1):
                if path.is_dir() and not path.is_symlink():
                    zf.writestr(arcname.rstrip("/") + "/", b"")
                else:
                    zf.write(path, arcname)
                if i % 50 == 0 or i == len(entries):
                    _notify(progress, f"ZIP {i}/{len(entries)}…", i / max(len(entries), 1))
        os.replace(temp, output_path)
        codec = "deflate"
    elif fmt in {"tarxz", "txz", "tar.xz"}:
        _notify(progress, "建立 TAR.XZ…", 0.10)
        temp = output_path.with_suffix(output_path.suffix + ".tmp")
        with tarfile.open(temp, "w:xz", preset=9 | lzma.PRESET_EXTREME, format=tarfile.PAX_FORMAT) as tf:
            for path, arcname in entries:
                tf.add(path, arcname=arcname, recursive=False)
        os.replace(temp, output_path)
        codec = "lzma2-xz"
    elif fmt == "rayz":
        with tempfile.TemporaryDirectory(prefix="raypack-") as td:
            td_path = Path(td)
            tar_path = td_path / "payload.tar"
            _create_tar(entries, tar_path, progress)
            tar_sha = _sha256_file(tar_path)
            if profile == "fast":
                chosen_codec = "zstd"
                candidate = td_path / "payload.zst"
                _compress_zstd(tar_path, candidate, progress)
            elif profile == "autobest":
                lzma_candidate = td_path / "payload.xz"
                brotli_candidate = td_path / "payload.br"
                _compress_lzma(tar_path, lzma_candidate, "ultra", progress)
                _compress_brotli(tar_path, brotli_candidate, progress)
                if brotli_candidate.stat().st_size < lzma_candidate.stat().st_size:
                    chosen_codec = "brotli"
                    candidate = brotli_candidate
                else:
                    chosen_codec = "lzma2-xz"
                    candidate = lzma_candidate
            else:
                chosen_codec = "lzma2-xz"
                candidate = td_path / "payload.xz"
                _compress_lzma(tar_path, candidate, profile, progress)
            metadata = {"format": "RAYZ", "format_version": 1, "app": "RayPack", "app_version": __version__, "author": __author__, "codec": chosen_codec, "profile": profile, "payload": "tar", "tar_sha256": tar_sha, "tar_size": tar_path.stat().st_size, "source_count": len(inputs)}
            _notify(progress, f"選用 {chosen_codec}，寫入 RAYZ…", 0.90)
            _write_rayz(output_path, candidate, metadata)
            codec = chosen_codec
    else:
        raise RayPackError(f"不支援的輸出格式：{format}")
    elapsed = time.monotonic() - start
    _notify(progress, "完成。", 1.0)
    return OperationResult(output=output_path, input_bytes=input_bytes, output_bytes=output_path.stat().st_size, codec=codec, profile=profile, elapsed_seconds=elapsed)


def _detect_format(path: Path) -> str:
    lower = path.name.lower()
    if lower.endswith(".rayz"):
        return "rayz"
    if lower.endswith(".zip") or lower.endswith(".jar") or lower.endswith(".mrpack") or lower.endswith(".mcpack"):
        return "zip"
    if lower.endswith((".tar.xz", ".txz", ".tar.gz", ".tgz", ".tar.bz2", ".tbz2", ".tar")):
        return "tar"
    raise RayPackError(f"無法判定封存格式：{path.name}")


def list_archive(path: str | os.PathLike[str]) -> list[ArchiveEntry]:
    archive = Path(path).expanduser().resolve()
    fmt = _detect_format(archive)
    if fmt == "zip":
        with zipfile.ZipFile(archive, "r") as zf:
            return [ArchiveEntry(i.filename, i.file_size, i.is_dir()) for i in zf.infolist()]
    if fmt == "tar":
        with tarfile.open(archive, "r:*") as tf:
            return [ArchiveEntry(m.name, m.size, m.isdir()) for m in tf.getmembers()]
    with tempfile.TemporaryDirectory(prefix="raypack-list-") as td:
        tar_path = Path(td) / "payload.tar"
        _decompress_rayz_to_tar(archive, tar_path)
        with tarfile.open(tar_path, "r") as tf:
            return [ArchiveEntry(m.name, m.size, m.isdir()) for m in tf.getmembers()]


def extract_archive(path: str | os.PathLike[str], destination: str | os.PathLike[str], *, progress: ProgressCallback | None = None) -> Path:
    archive = Path(path).expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    fmt = _detect_format(archive)
    _notify(progress, "檢查封存內容…", 0.10)
    if fmt == "zip":
        with zipfile.ZipFile(archive, "r") as zf:
            bad = zf.testzip()
            if bad:
                raise RayPackError(f"ZIP CRC 驗證失敗：{bad}")
            _safe_extract_zip(zf, dest)
    elif fmt == "tar":
        with tarfile.open(archive, "r:*") as tf:
            _safe_extract_tar(tf, dest)
    else:
        with tempfile.TemporaryDirectory(prefix="raypack-extract-") as td:
            tar_path = Path(td) / "payload.tar"
            _decompress_rayz_to_tar(archive, tar_path, progress)
            with tarfile.open(tar_path, "r") as tf:
                _safe_extract_tar(tf, dest)
    _notify(progress, "解壓縮完成。", 1.0)
    return dest


def verify_archive(path: str | os.PathLike[str]) -> dict[str, object]:
    archive = Path(path).expanduser().resolve()
    fmt = _detect_format(archive)
    if fmt == "zip":
        with zipfile.ZipFile(archive, "r") as zf:
            bad = zf.testzip()
            if bad:
                return {"ok": False, "format": "zip", "error": f"CRC failed: {bad}"}
            for info in zf.infolist():
                _safe_member_path(info.filename)
            return {"ok": True, "format": "zip", "entries": len(zf.infolist())}
    if fmt == "tar":
        with tarfile.open(archive, "r:*") as tf:
            _validate_tar_members(tf)
            members = tf.getmembers()
            return {"ok": True, "format": "tar", "entries": len(members)}
    with tempfile.TemporaryDirectory(prefix="raypack-verify-") as td:
        tar_path = Path(td) / "payload.tar"
        meta = _decompress_rayz_to_tar(archive, tar_path)
        with tarfile.open(tar_path, "r") as tf:
            _validate_tar_members(tf)
            entries = len(tf.getmembers())
        return {"ok": True, "format": "rayz", "entries": entries, "codec": meta.get("codec"), "profile": meta.get("profile"), "payload_sha256": meta.get("tar_sha256")}
