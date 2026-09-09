# Third-Party Notices

RayPack 本身為 proprietary / All Rights Reserved；以下第三方元件不受 RayPack proprietary 條款取代。

- **Python** — Python Software Foundation License.
- **Brotli** — MIT-style license.
- **python-zstandard / Zstandard** — BSD license.
- **Pillow** — HPND license.
- **PyInstaller** — GPL with the PyInstaller bootloader exception applicable to generated executables.
- **FFmpeg video runtime** — FFmpeg 8.1.2 LGPL-only Windows build from `serversideup/ffmpeg-lgpl-builds`, release `v8.1.2-27`. The build is configured with GPL/nonfree disabled. Upstream project: https://github.com/serversideup/ffmpeg-lgpl-builds ; FFmpeg source: https://ffmpeg.org/
- **FFmpeg audio runtime / LAME** — `acoustid/ffmpeg-build` FFmpeg 8.1.2 `audio-encode` Windows build, release `v8.1.2-1`, used for LGPL FFmpeg plus `libmp3lame`. Build/source project: https://github.com/acoustid/ffmpeg-build ; LAME project: https://lame.sourceforge.io/

The Windows workflow pins and SHA-256-verifies the exact FFmpeg archives before bundling their executables. The video runtime also carries the DLLs shipped by that verified archive (`libvpl-2.dll`, `libwinpthread-1.dll`, `libopenh264-7.dll`) so the packaged FFmpeg can load its declared Windows runtime dependencies. Users may replace the bundled FFmpeg executables with compatible versions by setting RayPack's documented environment variables (`RAYPACK_FFMPEG_VIDEO`, `RAYPACK_FFPROBE_VIDEO`, `RAYPACK_FFMPEG_AUDIO`, `RAYPACK_FFPROBE_AUDIO`) when running from source.
