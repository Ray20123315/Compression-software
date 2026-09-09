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
from .media import restore_smart_files, stage_smart_inputs

ProgressCallback = Callable[[str, float | None], None]
MAGIC = b"RAYZ\x01"
HEADER_STRUCT = struct.Struct("<I")
BUFFER_SIZE = 1024 * 1024
COMPRESSED_EXTENSIONS = {".7z", ".aac", ".avi", ".avif", ".br", ".bz2", ".flac", ".gif", ".gz", ".jar", ".jpeg", ".jpg", ".lz4", ".m4a", ".mkv", ".mov", ".mp3", ".mp4", ".ogg", ".opus", ".png", ".rar", ".webm", ".webp", ".xz", ".zip", ".zst"}
TEXT_EXTENSIONS = {".cfg", ".conf", ".css", ".csv", ".ini", ".java", ".js", ".json", ".kt", ".lang", ".lua", ".mcfunction", ".mcmeta", ".md", ".properties", ".py", ".toml", ".ts", ".txt", ".xml", ".yaml", ".yml"}

class RayPackError(Exception): pass
class ArchiveSecurityError(RayPackError): pass

@dataclass(frozen=True)
class ArchiveEntry:
    name: str; size: int; is_dir: bool

@dataclass(frozen=True)
class OperationResult:
    output: Path; input_bytes: int; output_bytes: int; codec: str; profile: str; elapsed_seconds: float
    @property
    def ratio(self) -> float: return (self.output_bytes / self.input_bytes) if self.input_bytes else 0.0

def _notify(callback, message, fraction=None):
    if callback: callback(message, fraction)

def _sha256_file(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        while chunk:=f.read(BUFFER_SIZE): h.update(chunk)
    return h.hexdigest()

def _safe_member_path(name: str) -> PurePosixPath:
    candidate=PurePosixPath(name.replace('\\','/'))
    if candidate.is_absolute() or any(p in {'..',''} for p in candidate.parts): raise ArchiveSecurityError(f"不安全的封存路徑：{name}")
    if candidate.parts and candidate.parts[0].endswith(':'): raise ArchiveSecurityError(f"不安全的磁碟機路徑：{name}")
    return candidate

def _safe_link_target(member_name, link_name):
    target=PurePosixPath(link_name.replace('\\','/'))
    if target.is_absolute(): raise ArchiveSecurityError(f"不安全的符號連結：{member_name} -> {link_name}")
    parts=[]
    for part in (PurePosixPath(member_name).parent/target).parts:
        if part in ('','.'): continue
        if part=='..':
            if not parts: raise ArchiveSecurityError(f"符號連結超出輸出目錄：{member_name} -> {link_name}")
            parts.pop()
        else: parts.append(part)

def _validate_tar_members(tf):
    for m in tf.getmembers():
        _safe_member_path(m.name)
        if m.issym() or m.islnk(): _safe_link_target(m.name,m.linkname)

def _safe_extract_tar(tf, destination):
    _validate_tar_members(tf); destination.mkdir(parents=True,exist_ok=True)
    try: tf.extractall(destination,filter='data')
    except TypeError: tf.extractall(destination)

def _safe_extract_zip(zf,destination):
    destination.mkdir(parents=True,exist_ok=True); root=destination.resolve()
    for info in zf.infolist():
        rel=_safe_member_path(info.filename); target=(destination/Path(*rel.parts)).resolve()
        if os.path.commonpath([str(root),str(target)])!=str(root): raise ArchiveSecurityError(f"ZIP 項目超出輸出目錄：{info.filename}")
    zf.extractall(destination)

def _flatten_inputs(inputs: Sequence[Path], minecraft_order=False):
    if not inputs: raise RayPackError('至少需要一個輸入檔案或資料夾。')
    tops=set(); entries=[]
    for source in inputs:
        source=source.expanduser().resolve()
        if not source.exists() and not source.is_symlink(): raise FileNotFoundError(str(source))
        top=source.name or source.anchor.replace(':','') or 'root'
        if top in tops: raise RayPackError(f"輸入頂層名稱重複：{top}")
        tops.add(top)
        if source.is_dir() and not source.is_symlink():
            entries.append((source,top))
            for child in source.rglob('*'): entries.append((child,f"{top}/{child.relative_to(source).as_posix()}"))
        else: entries.append((source,top))
    def key(item):
        p,a=item
        if p.is_dir() and not p.is_symlink(): return (0,a.count('/'),a.lower())
        if not minecraft_order: return (1,a.count('/'),a.lower())
        ext=p.suffix.lower(); rank=1 if ext in TEXT_EXTENSIONS else 3 if ext in COMPRESSED_EXTENSIONS else 2
        return (rank,a.count('/'),a.lower())
    return sorted(entries,key=key)

def _input_size(entries):
    total=0; seen=set()
    for p,_ in entries:
        try: st=p.stat(follow_symlinks=False)
        except (FileNotFoundError,OSError): continue
        if p.is_file() and not p.is_symlink():
            key=(getattr(st,'st_dev',0),getattr(st,'st_ino',id(p)))
            if key not in seen: seen.add(key); total+=st.st_size
    return total

def _create_tar(entries, tar_path, progress=None):
    _notify(progress,'建立 solid 封裝資料流…',0.05); total=max(len(entries),1)
    with tarfile.open(tar_path,'w',format=tarfile.PAX_FORMAT,dereference=False) as tf:
        for i,(p,a) in enumerate(entries,1):
            tf.add(p,arcname=a,recursive=False)
            if i%50==0 or i==total: _notify(progress,f"封裝 {i}/{total} 個項目…",0.05+(i/total)*0.20)

def _lzma_filters(profile):
    if profile=='balanced': ds,n=32*1024*1024,128
    elif profile=='minecraft': ds,n=128*1024*1024,273
    else: ds,n=192*1024*1024,273
    return [{'id':lzma.FILTER_LZMA2,'dict_size':ds,'lc':3,'lp':0,'pb':2,'mode':lzma.MODE_NORMAL,'nice_len':n,'mf':lzma.MF_BT4,'depth':0}]

def _compress_lzma(tar_path,out_path,profile,progress=None):
    _notify(progress,'LZMA2 高壓縮中…',0.35)
    with tar_path.open('rb') as src,lzma.open(out_path,'wb',format=lzma.FORMAT_XZ,check=lzma.CHECK_CRC64,filters=_lzma_filters(profile)) as dst:
        shutil.copyfileobj(src,dst,BUFFER_SIZE)

def _compress_brotli(tar_path,out_path,progress=None):
    _notify(progress,'Brotli q11 候選壓縮中…',0.55); c=brotli.Compressor(mode=brotli.MODE_GENERIC,quality=11,lgwin=24)
    with tar_path.open('rb') as src,out_path.open('wb') as dst:
        while chunk:=src.read(BUFFER_SIZE):
            part=c.process(chunk)
            if part: dst.write(part)
        dst.write(c.finish())

def _compress_zstd(tar_path,out_path,progress=None):
    if zstd is None: raise RayPackError('Fast Zstd 需要 zstandard 套件；正式 Windows 版已內建。')
    _notify(progress,'Zstd 快速壓縮中…',0.40); c=zstd.ZstdCompressor(level=12,threads=-1,write_checksum=True)
    with tar_path.open('rb') as src,out_path.open('wb') as raw:
        with c.stream_writer(raw,closefd=False) as dst: shutil.copyfileobj(src,dst,BUFFER_SIZE)

def _write_rayz(output,payload,metadata):
    encoded=json.dumps(metadata,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
    if len(encoded)>1024*1024: raise RayPackError('RAYZ metadata 過大。')
    temp=output.with_suffix(output.suffix+'.tmp')
    with temp.open('wb') as dst,payload.open('rb') as src:
        dst.write(MAGIC); dst.write(HEADER_STRUCT.pack(len(encoded))); dst.write(encoded); shutil.copyfileobj(src,dst,BUFFER_SIZE)
    os.replace(temp,output)

def _read_rayz_header(path):
    with path.open('rb') as fh:
        if fh.read(len(MAGIC))!=MAGIC: raise RayPackError('不是有效的 RAYZ 檔案或格式版本不支援。')
        raw=fh.read(HEADER_STRUCT.size)
        if len(raw)!=HEADER_STRUCT.size: raise RayPackError('RAYZ 標頭損毀。')
        (n,)=HEADER_STRUCT.unpack(raw)
        if n<=0 or n>1024*1024: raise RayPackError('RAYZ metadata 長度異常。')
        data=fh.read(n)
        if len(data)!=n: raise RayPackError('RAYZ metadata 不完整。')
        try: meta=json.loads(data.decode())
        except Exception as e: raise RayPackError('RAYZ metadata 無法解析。') from e
        return meta,len(MAGIC)+HEADER_STRUCT.size+n

def _decompress_rayz_to_tar(path,tar_path,progress=None):
    meta,offset=_read_rayz_header(path); codec=str(meta.get('codec','')); _notify(progress,f"解碼 {codec} 資料流…",0.20)
    with path.open('rb') as raw:
        raw.seek(offset)
        if codec=='lzma2-xz':
            with lzma.LZMAFile(raw,'rb') as src,tar_path.open('wb') as dst: shutil.copyfileobj(src,dst,BUFFER_SIZE)
        elif codec=='brotli':
            d=brotli.Decompressor()
            with tar_path.open('wb') as dst:
                while chunk:=raw.read(BUFFER_SIZE):
                    part=d.process(chunk)
                    if part: dst.write(part)
                if not d.is_finished(): raise RayPackError('Brotli 資料流不完整。')
        elif codec=='zstd':
            if zstd is None: raise RayPackError('此 RAYZ 使用 Zstd；目前環境缺少 zstandard 套件。')
            with zstd.ZstdDecompressor().stream_reader(raw) as src,tar_path.open('wb') as dst: shutil.copyfileobj(src,dst,BUFFER_SIZE)
        else: raise RayPackError(f"不支援的 RAYZ codec：{codec}")
    expected=meta.get('tar_sha256')
    if expected and _sha256_file(tar_path)!=expected: raise RayPackError('RAYZ 完整性驗證失敗：payload SHA-256 不符。')
    return meta

def _rayz_from_tar(tar_path: Path, out: Path, profile: str, source_count: int, *, smart_manifest=None, progress=None):
    tar_sha=_sha256_file(tar_path)
    if profile=='fast':
        codec='zstd'; candidate=out.parent/'payload.zst'; _compress_zstd(tar_path,candidate,progress)
    elif profile=='autobest':
        xz=out.parent/'payload.xz'; br=out.parent/'payload.br'; _compress_lzma(tar_path,xz,'ultra',progress); _compress_brotli(tar_path,br,progress)
        codec,candidate=('brotli',br) if br.stat().st_size<xz.stat().st_size else ('lzma2-xz',xz)
    else:
        codec='lzma2-xz'; candidate=out.parent/'payload.xz'; _compress_lzma(tar_path,candidate,'ultra' if profile=='smart' else profile,progress)
    meta={'format':'RAYZ','format_version':1,'app':'RayPack','app_version':__version__,'author':__author__,'codec':codec,'profile':profile,'payload':'tar','tar_sha256':tar_sha,'tar_size':tar_path.stat().st_size,'source_count':source_count}
    if smart_manifest is not None:
        meta['smart_media']={'lossy':True,'restore_dimensions_only':True,'disclaimer':'Smart Media restores dimensions/sample rate/container usability, not discarded original detail.','manifest':smart_manifest}
    _write_rayz(out,candidate,meta); return codec

def compress_archive(inputs: Sequence[str|os.PathLike[str]], output: str|os.PathLike[str], *, format='rayz', profile='autobest', progress=None):
    start=time.monotonic(); output_path=Path(output).expanduser().resolve(); output_path.parent.mkdir(parents=True,exist_ok=True)
    fmt=format.lower().replace('.',''); profile=profile.lower()
    allowed={'autobest','ultra','balanced','fast','minecraft','smart'}
    if profile not in allowed: raise RayPackError(f"未知壓縮模式：{profile}")
    source_paths=[Path(p) for p in inputs]; original_entries=_flatten_inputs(source_paths,minecraft_order=(profile=='minecraft')); input_bytes=_input_size(original_entries)
    if any(p.resolve()==output_path for p,_ in original_entries if p.exists()): raise RayPackError('輸出檔案不能同時是輸入檔案。')
    if profile=='smart' and fmt!='rayz': raise RayPackError('Smart Media 需要 RAYZ 格式保存還原 metadata。')
    if fmt=='zip':
        temp=output_path.with_suffix(output_path.suffix+'.tmp')
        with zipfile.ZipFile(temp,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=9,allowZip64=True) as zf:
            for p,a in original_entries:
                if p.is_dir() and not p.is_symlink(): zf.writestr(a.rstrip('/')+'/',b'')
                else: zf.write(p,a)
        os.replace(temp,output_path); codec='deflate'
    elif fmt in {'tarxz','txz','tar.xz'}:
        temp=output_path.with_suffix(output_path.suffix+'.tmp')
        with tarfile.open(temp,'w:xz',preset=9|lzma.PRESET_EXTREME,format=tarfile.PAX_FORMAT) as tf:
            for p,a in original_entries: tf.add(p,arcname=a,recursive=False)
        os.replace(temp,output_path); codec='lzma2-xz'
    elif fmt=='rayz':
        with tempfile.TemporaryDirectory(prefix='raypack-') as td:
            td=Path(td)
            if profile!='smart':
                tar_path=td/'payload.tar'; _create_tar(original_entries,tar_path,progress); codec=_rayz_from_tar(tar_path,output_path,profile,len(inputs),progress=progress)
            else:
                _notify(progress,'建立 Exact 與 Smart Media 候選…',0.03)
                exact_tar=td/'exact.tar'; _create_tar(original_entries,exact_tar,None); exact_rayz=td/'exact.rayz'; _rayz_from_tar(exact_tar,exact_rayz,'ultra',len(inputs))
                stage=td/'smart-stage'; stage.mkdir(); staged,manifest=stage_smart_inputs(source_paths,stage)
                if not manifest:
                    shutil.copy2(exact_rayz,output_path); codec='lzma2-xz'
                else:
                    smart_entries=_flatten_inputs(staged); smart_tar=td/'smart.tar'; _create_tar(smart_entries,smart_tar,None); smart_rayz=td/'smart.rayz'; _rayz_from_tar(smart_tar,smart_rayz,'smart',len(inputs),smart_manifest=manifest)
                    if smart_rayz.stat().st_size < exact_rayz.stat().st_size:
                        shutil.copy2(smart_rayz,output_path); codec='lzma2-xz-smart'
                    else:
                        shutil.copy2(exact_rayz,output_path); codec='lzma2-xz-exact-fallback'
    else: raise RayPackError(f"不支援的輸出格式：{format}")
    _notify(progress,'完成。',1.0); elapsed=time.monotonic()-start
    return OperationResult(output_path,input_bytes,output_path.stat().st_size,codec,profile,elapsed)

def _detect_format(path):
    lower=path.name.lower()
    if lower.endswith('.rayz'): return 'rayz'
    if lower.endswith(('.zip','.jar','.mrpack','.mcpack')): return 'zip'
    if lower.endswith(('.tar.xz','.txz','.tar.gz','.tgz','.tar.bz2','.tbz2','.tar')): return 'tar'
    raise RayPackError(f"無法判定封存格式：{path.name}")

def list_archive(path):
    a=Path(path).expanduser().resolve(); fmt=_detect_format(a)
    if fmt=='zip':
        with zipfile.ZipFile(a) as zf: return [ArchiveEntry(i.filename,i.file_size,i.is_dir()) for i in zf.infolist()]
    if fmt=='tar':
        with tarfile.open(a,'r:*') as tf: return [ArchiveEntry(m.name,m.size,m.isdir()) for m in tf.getmembers()]
    with tempfile.TemporaryDirectory(prefix='raypack-list-') as td:
        tp=Path(td)/'payload.tar'; _decompress_rayz_to_tar(a,tp)
        with tarfile.open(tp,'r') as tf: return [ArchiveEntry(m.name,m.size,m.isdir()) for m in tf.getmembers()]

def extract_archive(path,destination,*,progress=None):
    a=Path(path).expanduser().resolve(); d=Path(destination).expanduser().resolve(); fmt=_detect_format(a); _notify(progress,'檢查封存內容…',0.10)
    if fmt=='zip':
        with zipfile.ZipFile(a) as zf:
            bad=zf.testzip()
            if bad: raise RayPackError(f"ZIP CRC 驗證失敗：{bad}")
            _safe_extract_zip(zf,d)
    elif fmt=='tar':
        with tarfile.open(a,'r:*') as tf: _safe_extract_tar(tf,d)
    else:
        with tempfile.TemporaryDirectory(prefix='raypack-extract-') as td:
            tp=Path(td)/'payload.tar'; meta=_decompress_rayz_to_tar(a,tp,progress)
            with tarfile.open(tp,'r') as tf: _safe_extract_tar(tf,d)
            smart=meta.get('smart_media')
            if isinstance(smart,dict) and smart.get('lossy'):
                manifest=smart.get('manifest',[])
                if isinstance(manifest,list): _notify(progress,'恢復 Smart Media 尺寸/取樣率…',0.85); restore_smart_files(d,manifest)
    _notify(progress,'解壓縮完成。',1.0); return d

def verify_archive(path):
    a=Path(path).expanduser().resolve(); fmt=_detect_format(a)
    if fmt=='zip':
        with zipfile.ZipFile(a) as zf:
            bad=zf.testzip()
            if bad: return {'ok':False,'format':'zip','error':f'CRC failed: {bad}'}
            for i in zf.infolist(): _safe_member_path(i.filename)
            return {'ok':True,'format':'zip','entries':len(zf.infolist())}
    if fmt=='tar':
        with tarfile.open(a,'r:*') as tf: _validate_tar_members(tf); return {'ok':True,'format':'tar','entries':len(tf.getmembers())}
    with tempfile.TemporaryDirectory(prefix='raypack-verify-') as td:
        tp=Path(td)/'payload.tar'; meta=_decompress_rayz_to_tar(a,tp)
        with tarfile.open(tp,'r') as tf: _validate_tar_members(tf); entries=len(tf.getmembers())
        smart=meta.get('smart_media') if isinstance(meta.get('smart_media'),dict) else None
        return {'ok':True,'format':'rayz','entries':entries,'codec':meta.get('codec'),'profile':meta.get('profile'),'payload_sha256':meta.get('tar_sha256'),'smart_media':bool(smart and smart.get('lossy')),'smart_transformations':len(smart.get('manifest',[])) if smart else 0}
