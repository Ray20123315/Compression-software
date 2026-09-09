# RayPack

**作者：ray20123315**  
**Copyright © 2026 ray20123315. All Rights Reserved.**

RayPack 是給 Windows 使用者的無損壓縮／解壓工具，重點是「好操作、可驗證、對 Minecraft 整合包友善」，並在適合的資料型態上盡可能追求比一般 7-Zip 設定更小的封存檔。

> 重要：沒有任何無損壓縮器可以保證所有資料都比 7-Zip 小。`.jpg`、`.png`、`.mp4`、`.mp3`、`.jar`、`.zip` 等本身通常已壓縮，再壓一次常只會小一點點，甚至變大。RayPack 不會偷偷降低圖片／影片／音訊品質，也不會拆開重包 Mod JAR 來換取數字上的縮小。

## 下載與使用

1. 到本專案 GitHub 的 **Releases**。
2. 下載最新的 `RayPack_v0.0.1.exe`。
3. 直接執行，不需要安裝 Python。
4. 在「壓縮」頁加入檔案或資料夾，選擇模式與格式後按 **開始壓縮**。
5. 在「解壓 / 檢查」頁可以讀取內容、驗證封存完整性，再解壓縮。

Windows 第一次執行未簽章的個人開發程式時，Microsoft SmartScreen 可能顯示警告。Release 版目前沒有商業程式碼簽章憑證；請從本專案官方 Release 下載並核對 SHA-256。

## 壓縮模式

| 模式 | 適合情境 | 作法 |
|---|---|---|
| **AutoBest** | 最在乎檔案大小 | 同一份 solid TAR 分別嘗試高壓縮 LZMA2 與 Brotli q11，最後保留較小候選；最慢、暫存空間需求最高 |
| **Ultra** | 備份、封存 | 192 MiB LZMA2 dictionary、BT4、nice length 273 |
| **Minecraft** | Java 整合包、伺服器資料夾、資源資料 | 保持所有檔案原始 bytes；先排列 JSON/TOML/CFG/script 等高可壓縮資料，再處理 JAR/ZIP/圖片/影音，減少 solid dictionary 被已壓縮資料污染 |
| **Balanced** | 一般使用 | 32 MiB LZMA2 dictionary，降低記憶體需求 |
| **Fast** | 大型資料、速度優先 | Zstd level 12，多執行緒 |

### Minecraft 整合包注意事項

RayPack 可以直接封存整個 Minecraft instance／伺服器資料夾，也能處理其中的 `.jar`、設定檔、resource pack、shader pack、世界存檔等。

- **不會解包再重包 `.jar`**：避免簽章失效或位元內容改變。
- **不會刪除 `logs`、cache 或其他檔案**：壓縮工具應完整還原；如果你想瘦身，請先自行刪除不需要的資料。
- `.jar` 本質上是 ZIP，很多 Mod 已經壓縮得很緊，因此真正能省空間的常是設定、腳本、JSON、log、未壓縮 NBT/資料檔等。
- Minecraft resource/data pack 若允許「最佳化內容本身」而非 byte-for-byte 還原，可以使用專門的 PackSquash 類工具得到更大縮減；那與 RayPack 的無損封存目標不同。

## 支援格式

### 建立
- `.rayz` — RayPack 原生格式，支援 LZMA2/XZ、Brotli 或 Zstd payload。
- `.zip` — 使用 Deflate，交換相容性最好。
- `.tar.xz` — 標準 TAR + XZ。

### 解壓／讀取／驗證
- `.rayz`
- `.zip`, `.jar`, `.mrpack`, `.mcpack`
- `.tar`, `.tar.xz`, `.txz`, `.tar.gz`, `.tgz`, `.tar.bz2`, `.tbz2`

RayPack 解壓前會檢查 path traversal（例如 `../evil.exe`）及危險 symlink 目標。

## CLI

主程式 `RayPack_v0.0.1.exe` 是 GUI。若要在 PowerShell/CMD 使用指令列，下載同一個 Release 裡的 `RayPackCLI_v0.0.1.exe`：

```powershell
RayPackCLI_v0.0.1.exe compress "D:\Minecraft\MyPack" -o "D:\Backup\MyPack.rayz" -p minecraft
RayPackCLI_v0.0.1.exe verify "D:\Backup\MyPack.rayz"
RayPackCLI_v0.0.1.exe list "D:\Backup\MyPack.rayz"
RayPackCLI_v0.0.1.exe extract "D:\Backup\MyPack.rayz" -o "D:\Restore"
```

其他格式：

```powershell
RayPackCLI_v0.0.1.exe compress .\MyFolder -o .\MyFolder.zip -f zip -p balanced
RayPackCLI_v0.0.1.exe compress .\MyFolder -o .\MyFolder.tar.xz -f tar.xz -p ultra
```

## 壓縮率與 7-Zip

RayPack 的目標是「在合適資料集上匹配或超過常見 7-Zip 設定」，不是宣稱新的資訊理論突破。壓縮率取決於內容：

- 大量文字、JSON、設定檔、重複資料：solid LZMA2 / Brotli 常有較大發揮空間。
- Minecraft Mod JAR、PNG/JPG、MP4、MP3：常已壓縮，可再縮空間有限。
- AutoBest 需要把 solid TAR 暫存並跑多個候選，因此峰值磁碟使用量會明顯高於單次壓縮。

如果要嚴格比較，請在同一批檔案、同一台電腦、相同「無損」前提下，記錄：輸入 bytes、輸出 bytes、壓縮時間、解壓時間與峰值 RAM；不要只比較預設 GUI 選項名稱。

## 從原始碼執行

需要 Python 3.11+：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
python -m raypack
```

執行測試：

```powershell
pip install -r requirements-build.txt
pytest -q
```

產生 Icon：

```powershell
python scripts\make_icon.py
```

## 建置 Windows EXE

GitHub Actions 會在 Windows runner 上：

1. 安裝依賴。
2. 產生 `RayPack.ico`。
3. 執行 pytest。
4. 使用 PyInstaller 建立單檔 `RayPack_v0.0.1.exe` 並嵌入作者、版本、Copyright 與 Icon。
5. 計算 `RayPack_v0.0.1.exe.sha256`。
6. 建立 GitHub Release 並上傳 EXE 與 SHA-256。

## 授權

RayPack 原始碼、程式、品牌與文件：**Copyright © 2026 ray20123315. All Rights Reserved.**  
完整條款見 [`LICENSE`](LICENSE)。第三方套件的授權見 [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md)。
