# RayPack v0.0.2

RayPack 是由 **ray20123315** 製作的 Windows 壓縮／解壓縮工具。一般備份可使用 Exact 模式完整還原原始 bytes；若你接受畫質／音質損失以換取更小體積，可選擇 **Smart Media（有損・更小）**。

## 下載

正式 Windows 版請到 GitHub Releases 下載：

- GUI：`RayPack_v0.0.2.exe`
- CLI：`RayPackCLI_v0.0.2.exe`
- 建議同時下載相同檔名的 `.sha256` 驗證檔案。

## 模式

- **Smart Media（有損・更小）**：僅 RAYZ。JPG/PNG 會縮小後以 WebP 保存；MP4 會降低解析度／bitrate；MP3 會降低 bitrate／sample rate。解壓時會恢復原始 pixel dimensions 或 sample rate，但**不會恢復已丟棄的原始細節**。若 Smart 最終檔案沒有比 Exact Ultra 小，會自動保存 Exact 候選。
- **AutoBest（Exact）**：比較 LZMA2 與 Brotli q11，保留較小結果。
- **Ultra（Exact）**：高壓縮 LZMA2。
- **Minecraft（Exact）**：依整合包資料型態排序 solid stream，不解包或改寫 Mod。
- **Balanced（Exact）**：較低記憶體需求。
- **Fast（Exact）**：Zstd level 12，多執行緒。

## JPG / PNG / MP4 / MP3 / JAR / ZIP

Smart Media 會針對圖片與影音做有損縮減。JAR/ZIP 則只在安全條件成立時做 logical optimization：未簽章 JAR、未加密、無重複 entry、沒有危險路徑且壓縮方法可處理。偵測到 signed JAR 或其他風險時會 Exact fallback。

> 「解壓時恢復解析度」只代表輸出尺寸／sample rate 回到原規格；降低解析度或 bitrate 時丟掉的資訊不能無損重建。

## 支援解壓格式

`.rayz`、`.zip`、`.jar`、`.mrpack`、`.mcpack`、`.tar`、`.tar.xz` / `.txz`、`.tar.gz` / `.tgz`、`.tar.bz2` / `.tbz2`。

## CLI

```powershell
RayPackCLI_v0.0.2.exe compress input.mp4 -o output.rayz -p smart
RayPackCLI_v0.0.2.exe verify output.rayz --json
RayPackCLI_v0.0.2.exe extract output.rayz -o restored
RayPackCLI_v0.0.2.exe doctor --json
```

## 授權與注意事項

RayPack 本身：Copyright © 2026 ray20123315. All Rights Reserved. 詳見 `LICENSE`。第三方元件仍受各自授權約束，詳見 `THIRD_PARTY_NOTICES.md`。

Windows EXE 目前沒有商業 Authenticode 憑證，因此 SmartScreen 可能顯示未知發行者警告。
