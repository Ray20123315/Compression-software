from __future__ import annotations

import io
import os
import tarfile
import zipfile
from pathlib import Path

import pytest

from raypack.core import ArchiveSecurityError, compress_archive, extract_archive, list_archive, verify_archive


def _fixture_tree(root: Path) -> None:
    (root / "config").mkdir(parents=True)
    (root / "scripts").mkdir()
    (root / "mods").mkdir()
    (root / "config" / "settings.toml").write_text("feature=true\n" * 500, encoding="utf-8")
    (root / "scripts" / "startup.mcfunction").write_text("say RayPack\n" * 600, encoding="utf-8")
    (root / "readme.txt").write_text("minecraft modpack test\n" * 400, encoding="utf-8")
    with zipfile.ZipFile(root / "mods" / "example.jar", "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        zf.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\n")
        zf.writestr("data.bin", os.urandom(4096))


def _tree_bytes(root: Path) -> dict[str, bytes]:
    result = {}
    for path in root.rglob("*"):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


@pytest.mark.parametrize("profile", ["balanced", "ultra", "minecraft", "autobest"])
def test_rayz_round_trip(tmp_path: Path, profile: str) -> None:
    source = tmp_path / "pack"
    source.mkdir()
    _fixture_tree(source)
    before = _tree_bytes(source)
    archive = tmp_path / f"pack-{profile}.rayz"
    result = compress_archive([source], archive, format="rayz", profile=profile)
    assert archive.exists()
    assert result.output_bytes == archive.stat().st_size
    check = verify_archive(archive)
    assert check["ok"] is True
    assert check["format"] == "rayz"
    assert list_archive(archive)
    out = tmp_path / f"out-{profile}"
    extract_archive(archive, out)
    assert _tree_bytes(out / "pack") == before


def test_zip_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    _fixture_tree(source)
    archive = tmp_path / "data.zip"
    compress_archive([source], archive, format="zip", profile="balanced")
    assert verify_archive(archive)["ok"] is True
    out = tmp_path / "zip-out"
    extract_archive(archive, out)
    assert _tree_bytes(out / "data") == _tree_bytes(source)


def test_tar_xz_round_trip(tmp_path: Path) -> None:
    source = tmp_path / "data"
    source.mkdir()
    _fixture_tree(source)
    archive = tmp_path / "data.tar.xz"
    compress_archive([source], archive, format="tar.xz", profile="ultra")
    assert verify_archive(archive)["ok"] is True
    out = tmp_path / "tar-out"
    extract_archive(archive, out)
    assert _tree_bytes(out / "data") == _tree_bytes(source)


def test_rejects_zip_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "evil.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../outside.txt", b"owned")
    with pytest.raises(ArchiveSecurityError):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_rejects_tar_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "evil.tar"
    with tarfile.open(archive, "w") as tf:
        info = tarfile.TarInfo("../outside.txt")
        payload = b"owned"
        info.size = len(payload)
        tf.addfile(info, io.BytesIO(payload))
    with pytest.raises(ArchiveSecurityError):
        extract_archive(archive, tmp_path / "out")
    assert not (tmp_path / "outside.txt").exists()


def test_fast_zstd_round_trip_when_available(tmp_path: Path) -> None:
    pytest.importorskip("zstandard")
    source = tmp_path / "fast.txt"
    source.write_text("fast-zstd\n" * 2000, encoding="utf-8")
    archive = tmp_path / "fast.rayz"
    compress_archive([source], archive, format="rayz", profile="fast")
    check = verify_archive(archive)
    assert check["ok"] is True
    assert check["codec"] == "zstd"
    out = tmp_path / "fast-out"
    extract_archive(archive, out)
    assert (out / "fast.txt").read_bytes() == source.read_bytes()
