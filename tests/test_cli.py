from __future__ import annotations

from pathlib import Path

from raypack.cli import main


def test_cli_smoke(tmp_path: Path) -> None:
    src = tmp_path / "hello.txt"
    src.write_text("hello raypack\n" * 100, encoding="utf-8")
    archive = tmp_path / "hello.rayz"
    assert main(["compress", str(src), "-o", str(archive), "-p", "balanced"]) == 0
    assert main(["verify", str(archive)]) == 0
    assert main(["list", str(archive)]) == 0
    out = tmp_path / "out"
    assert main(["extract", str(archive), "-o", str(out)]) == 0
    assert (out / "hello.txt").read_bytes() == src.read_bytes()
