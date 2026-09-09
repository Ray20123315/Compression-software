from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from PIL import Image

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png"}
VIDEO_EXTENSIONS = {".mp4"}
AUDIO_EXTENSIONS = {".mp3"}
NESTED_ARCHIVE_EXTENSIONS = {".zip", ".jar"}
SIGNED_JAR_SUFFIXES = (".SF", ".RSA", ".DSA", ".EC")


def _safe_rel(name: str) -> PurePosixPath:
    value = PurePosixPath(name.replace("\\", "/"))
    if value.is_absolute() or any(part in {"", ".."} for part in value.parts):
        raise ValueError(f"unsafe nested archive path: {name}")
    if value.parts and value.parts[0].endswith(":"):
        raise ValueError(f"unsafe nested archive drive path: {name}")
    return value


def _bundle_root() -> Path | None:
    root = getattr(sys, "_MEIPASS", None)
    return Path(root) if root else None


def _tool_candidates(kind: str, tool: str) -> list[Path | str]:
    env_name = f"RAYPACK_{tool.upper()}_{kind.upper()}"
    out: list[Path | str] = []
    if os.environ.get(env_name):
        out.append(Path(os.environ[env_name]))
    root = _bundle_root()
    if root:
        exe = f"{tool}.exe" if os.name == "nt" else tool
        out.append(root / "raypack_tools" / kind / exe)
    out.append(tool)
    return out


def find_tool(kind: str, tool: str) -> str | None:
    for candidate in _tool_candidates(kind, tool):
        if isinstance(candidate, Path):
            if candidate.is_file():
                return str(candidate)
        else:
            resolved = shutil.which(candidate)
            if resolved:
                return resolved
    return None


def _run(cmd: list[str], *, timeout: int = 180) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, check=True)


def _probe(path: Path, kind: str) -> dict[str, Any] | None:
    ffprobe = find_tool(kind, "ffprobe") or find_tool("video", "ffprobe") or find_tool("audio", "ffprobe")
    if not ffprobe:
        return None
    try:
        cp = _run([ffprobe, "-v", "error", "-show_streams", "-of", "json", str(path)], timeout=45)
        return {"streams": json.loads(cp.stdout).get("streams", [])}
    except Exception:
        return None


def _encoder_available(kind: str, encoder: str) -> bool:
    ffmpeg = find_tool(kind, "ffmpeg")
    if not ffmpeg:
        return False
    try:
        cp = _run([ffmpeg, "-hide_banner", "-encoders"], timeout=45)
        return encoder in cp.stdout
    except Exception:
        return False


def _video_encoder() -> str | None:
    if _encoder_available("video", "libopenh264"):
        return "libopenh264"
    if _encoder_available("video", "mpeg4"):
        return "mpeg4"
    return None


def _video_encoder_args(encoder: str, *, restore: bool = False) -> list[str]:
    if encoder == "libopenh264":
        return ["-c:v", "libopenh264", "-b:v", "2500k" if restore else "650k", "-pix_fmt", "yuv420p"]
    return ["-c:v", "mpeg4", "-q:v", "5" if restore else "12"]


def doctor_report() -> dict[str, Any]:
    video_ffmpeg = find_tool("video", "ffmpeg")
    video_ffprobe = find_tool("video", "ffprobe")
    audio_ffmpeg = find_tool("audio", "ffmpeg") or video_ffmpeg
    audio_ffprobe = find_tool("audio", "ffprobe") or video_ffprobe
    try:
        import zstandard  # noqa: F401
        zstd_ok = True
    except ImportError:
        zstd_ok = False
    return {
        "pillow": True,
        "zstandard": zstd_ok,
        "video_ffmpeg": video_ffmpeg,
        "video_ffprobe": video_ffprobe,
        "video_libopenh264_encoder": _encoder_available("video", "libopenh264"),
        "video_mpeg4_encoder": _encoder_available("video", "mpeg4"),
        "video_smart_encoder": _video_encoder(),
        "audio_ffmpeg": audio_ffmpeg,
        "audio_ffprobe": audio_ffprobe,
        "audio_libmp3lame_encoder": _encoder_available("audio", "libmp3lame") or _encoder_available("video", "libmp3lame"),
    }


def _image_transform(path: Path) -> dict[str, Any] | None:
    try:
        with Image.open(path) as im:
            im.load()
            original_format = (im.format or path.suffix.lstrip(".")).upper()
            width, height = im.size
            if width < 4 or height < 4:
                return None
            target = (max(1, width // 2), max(1, height // 2))
            work = im.convert("RGB") if original_format in {"JPEG", "JPG"} else im.convert("RGBA" if "A" in im.getbands() else "RGB")
            work = work.resize(target, Image.Resampling.LANCZOS)
            buf = io.BytesIO()
            work.save(buf, format="WEBP", quality=72, method=6)
            transformed = buf.getvalue()
        if len(transformed) >= path.stat().st_size:
            return None
        path.write_bytes(transformed)
        return {"kind": "image", "original_format": original_format, "original_width": width, "original_height": height, "stored_width": target[0], "stored_height": target[1], "stored_format": "WEBP"}
    except Exception:
        return None


def _restore_image(path: Path, item: dict[str, Any]) -> None:
    with Image.open(path) as im:
        im.load()
        out = im.resize((int(item["original_width"]), int(item["original_height"])), Image.Resampling.LANCZOS)
        fmt = str(item.get("original_format") or "PNG").upper()
        tmp = path.with_name(path.name + ".restore.tmp")
        if fmt in {"JPEG", "JPG"}:
            out.convert("RGB").save(tmp, format="JPEG", quality=92, optimize=True)
        else:
            out.save(tmp, format="PNG", optimize=True)
        os.replace(tmp, path)


def _video_transform(path: Path) -> dict[str, Any] | None:
    ffmpeg = find_tool("video", "ffmpeg")
    info = _probe(path, "video")
    encoder = _video_encoder()
    if not ffmpeg or not info or not encoder:
        return None
    video = next((s for s in info["streams"] if s.get("codec_type") == "video"), None)
    if not video:
        return None
    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if width < 4 or height < 4:
        return None
    sw = max(2, (width // 2) // 2 * 2)
    sh = max(2, (height // 2) // 2 * 2)
    tmp = path.with_name(path.name + ".smart.mp4")
    try:
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vf", f"scale={sw}:{sh}:flags=lanczos,format=yuv420p", *_video_encoder_args(encoder), "-c:a", "aac", "-b:a", "80k", "-movflags", "+faststart", str(tmp)])
        if not tmp.exists() or tmp.stat().st_size >= path.stat().st_size:
            tmp.unlink(missing_ok=True)
            return None
        os.replace(tmp, path)
        return {"kind": "video", "original_width": width, "original_height": height, "stored_width": sw, "stored_height": sh}
    except Exception:
        tmp.unlink(missing_ok=True)
        return None


def _restore_video(path: Path, item: dict[str, Any]) -> None:
    ffmpeg = find_tool("video", "ffmpeg")
    encoder = _video_encoder()
    if not ffmpeg or not encoder:
        raise RuntimeError("Smart MP4 extraction requires bundled FFmpeg with a supported software video encoder")
    tmp = path.with_name(path.name + ".restore.mp4")
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vf", f"scale={int(item['original_width'])}:{int(item['original_height'])}:flags=lanczos,format=yuv420p", *_video_encoder_args(encoder, restore=True), "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(tmp)])
    os.replace(tmp, path)


def _audio_transform(path: Path) -> dict[str, Any] | None:
    ffmpeg = find_tool("audio", "ffmpeg") or find_tool("video", "ffmpeg")
    info = _probe(path, "audio")
    if not ffmpeg or not info or not (_encoder_available("audio", "libmp3lame") or _encoder_available("video", "libmp3lame")):
        return None
    audio = next((s for s in info["streams"] if s.get("codec_type") == "audio"), None)
    if not audio:
        return None
    original_rate = int(audio.get("sample_rate") or 44100)
    target_rate = 22050 if original_rate >= 44100 else max(16000, original_rate // 2)
    tmp = path.with_name(path.name + ".smart.mp3")
    try:
        _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-c:a", "libmp3lame", "-b:a", "80k", "-ar", str(target_rate), str(tmp)])
        if not tmp.exists() or tmp.stat().st_size >= path.stat().st_size:
            tmp.unlink(missing_ok=True)
            return None
        os.replace(tmp, path)
        return {"kind": "audio", "original_sample_rate": original_rate, "stored_sample_rate": target_rate}
    except Exception:
        tmp.unlink(missing_ok=True)
        return None


def _restore_audio(path: Path, item: dict[str, Any]) -> None:
    ffmpeg = find_tool("audio", "ffmpeg") or find_tool("video", "ffmpeg")
    if not ffmpeg or not (_encoder_available("audio", "libmp3lame") or _encoder_available("video", "libmp3lame")):
        raise RuntimeError("Smart MP3 extraction requires bundled FFmpeg with libmp3lame")
    tmp = path.with_name(path.name + ".restore.mp3")
    _run([ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(path), "-vn", "-c:a", "libmp3lame", "-b:a", "192k", "-ar", str(int(item["original_sample_rate"])), str(tmp)])
    os.replace(tmp, path)


def _nested_transform(path: Path) -> dict[str, Any] | None:
    is_jar = path.suffix.lower() == ".jar"
    try:
        with zipfile.ZipFile(path, "r") as zin:
            infos = zin.infolist()
            names = [i.filename for i in infos]
            if len(names) != len(set(names)):
                return None
            for info in infos:
                _safe_rel(info.filename)
                if info.flag_bits & 0x1:
                    return None
                if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED, zipfile.ZIP_BZIP2, zipfile.ZIP_LZMA}:
                    return None
            if is_jar and any(n.upper().startswith("META-INF/") and n.upper().endswith(SIGNED_JAR_SUFFIXES) for n in names):
                return None
            contents = [(i, zin.read(i.filename)) for i in infos]
        tmp = path.with_name(path.name + ".logical.tmp")
        with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zout:
            for info, data in contents:
                clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
                clone.external_attr = info.external_attr
                clone.create_system = info.create_system
                clone.comment = info.comment
                clone.extra = info.extra
                zout.writestr(clone, data, compress_type=zipfile.ZIP_STORED)
        os.replace(tmp, path)
        return {"kind": "nested_archive", "jar": is_jar}
    except Exception:
        try:
            tmp.unlink(missing_ok=True)  # type: ignore[name-defined]
        except Exception:
            pass
        return None


def _restore_nested(path: Path, item: dict[str, Any]) -> None:
    with zipfile.ZipFile(path, "r") as zin:
        contents = [(i, zin.read(i.filename)) for i in zin.infolist()]
    tmp = path.with_name(path.name + ".restore.zip")
    with zipfile.ZipFile(tmp, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9, allowZip64=True) as zout:
        for info, data in contents:
            clone = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            clone.external_attr = info.external_attr
            clone.create_system = info.create_system
            clone.comment = info.comment
            clone.extra = info.extra
            zout.writestr(clone, data, compress_type=zipfile.ZIP_DEFLATED)
    os.replace(tmp, path)


def stage_smart_inputs(inputs: list[Path], stage_root: Path) -> tuple[list[Path], list[dict[str, Any]]]:
    staged: list[Path] = []
    manifest: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in inputs:
        source = source.expanduser().resolve()
        top = source.name or "root"
        if top in seen:
            raise ValueError(f"duplicate top-level input name: {top}")
        seen.add(top)
        target = stage_root / top
        if source.is_dir() and not source.is_symlink():
            shutil.copytree(source, target, symlinks=True, copy_function=shutil.copy2)
        elif source.is_symlink():
            target.symlink_to(os.readlink(source), target_is_directory=source.is_dir())
        else:
            shutil.copy2(source, target)
        staged.append(target)
    for root in staged:
        candidates = [root] if root.is_file() else [p for p in root.rglob("*") if p.is_file() and not p.is_symlink()]
        for path in candidates:
            ext = path.suffix.lower()
            item: dict[str, Any] | None = None
            if ext in IMAGE_EXTENSIONS:
                item = _image_transform(path)
            elif ext in VIDEO_EXTENSIONS:
                item = _video_transform(path)
            elif ext in AUDIO_EXTENSIONS:
                item = _audio_transform(path)
            elif ext in NESTED_ARCHIVE_EXTENSIONS:
                item = _nested_transform(path)
            if item:
                item["path"] = path.relative_to(stage_root).as_posix()
                manifest.append(item)
    return staged, manifest


def restore_smart_files(destination: Path, manifest: list[dict[str, Any]]) -> None:
    root = destination.resolve()
    for item in manifest:
        rel = _safe_rel(str(item["path"]))
        path = (destination / Path(*rel.parts)).resolve()
        if os.path.commonpath([str(root), str(path)]) != str(root):
            raise ValueError(f"unsafe smart restore path: {item['path']}")
        kind = item.get("kind")
        if kind == "image":
            _restore_image(path, item)
        elif kind == "video":
            _restore_video(path, item)
        elif kind == "audio":
            _restore_audio(path, item)
        elif kind == "nested_archive":
            _restore_nested(path, item)
