from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import __version__
from .core import RayPackError, compress_archive, extract_archive, list_archive, verify_archive


def _human_size(value: int) -> str:
    units = ["B", "KiB", "MiB", "GiB", "TiB"]
    size = float(value)
    for unit in units:
        if abs(size) < 1024 or unit == units[-1]:
            return f"{size:.2f} {unit}"
        size /= 1024
    return f"{value} B"


def _progress(message: str, fraction: float | None) -> None:
    if fraction is None:
        print(message, file=sys.stderr)
    else:
        print(f"[{fraction * 100:5.1f}%] {message}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="raypack", description="RayPack 高壓縮封存工具")
    parser.add_argument("--version", action="version", version=f"RayPack {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("compress", help="壓縮檔案或資料夾")
    p.add_argument("inputs", nargs="+", help="輸入檔案/資料夾")
    p.add_argument("-o", "--output", required=True, help="輸出檔案")
    p.add_argument("-f", "--format", choices=["rayz", "zip", "tar.xz"], default="rayz")
    p.add_argument("-p", "--profile", choices=["autobest", "ultra", "balanced", "fast", "minecraft"], default="autobest")

    p = sub.add_parser("extract", help="解壓縮")
    p.add_argument("archive")
    p.add_argument("-o", "--output", required=True)

    p = sub.add_parser("list", help="列出封存內容")
    p.add_argument("archive")

    p = sub.add_parser("verify", help="驗證封存完整性與路徑安全")
    p.add_argument("archive")
    p.add_argument("--json", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "compress":
            result = compress_archive(args.inputs, args.output, format=args.format, profile=args.profile, progress=_progress)
            saving = 100 * (1 - result.ratio) if result.input_bytes else 0.0
            print(f"完成：{result.output}")
            print(f"輸入：{_human_size(result.input_bytes)}")
            print(f"輸出：{_human_size(result.output_bytes)}")
            print(f"節省：{saving:.2f}% | codec={result.codec} | {result.elapsed_seconds:.2f}s")
        elif args.command == "extract":
            print(extract_archive(args.archive, args.output, progress=_progress))
        elif args.command == "list":
            entries = list_archive(args.archive)
            for entry in entries:
                kind = "DIR " if entry.is_dir else "FILE"
                print(f"{kind:4} {_human_size(entry.size):>12}  {entry.name}")
            print(f"共 {len(entries)} 個項目")
        elif args.command == "verify":
            result = verify_archive(args.archive)
            if args.json:
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                print("驗證通過" if result.get("ok") else "驗證失敗")
                for key, value in result.items():
                    if key != "ok":
                        print(f"{key}: {value}")
            return 0 if result.get("ok") else 2
    except (RayPackError, OSError, ValueError) as exc:
        print(f"錯誤：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
