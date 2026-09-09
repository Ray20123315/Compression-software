from __future__ import annotations
import argparse, json, sys
from . import __version__
from .core import RayPackError, compress_archive, extract_archive, list_archive, verify_archive
from .media import doctor_report

def _human_size(v):
    s=float(v)
    for u in ('B','KiB','MiB','GiB','TiB'):
        if abs(s)<1024 or u=='TiB': return f'{s:.2f} {u}'
        s/=1024

def _progress(m,f): print((f'[{f*100:5.1f}%] ' if f is not None else '')+m,file=sys.stderr)
def build_parser():
    p=argparse.ArgumentParser(prog='raypack',description='RayPack 高壓縮封存工具'); p.add_argument('--version',action='version',version=f'RayPack {__version__}'); s=p.add_subparsers(dest='command',required=True)
    c=s.add_parser('compress',help='壓縮檔案或資料夾'); c.add_argument('inputs',nargs='+'); c.add_argument('-o','--output',required=True); c.add_argument('-f','--format',choices=['rayz','zip','tar.xz'],default='rayz'); c.add_argument('-p','--profile',choices=['autobest','ultra','balanced','fast','minecraft','smart'],default='autobest')
    e=s.add_parser('extract',help='解壓縮'); e.add_argument('archive'); e.add_argument('-o','--output',required=True)
    l=s.add_parser('list',help='列出封存內容'); l.add_argument('archive')
    v=s.add_parser('verify',help='驗證封存完整性與路徑安全'); v.add_argument('archive'); v.add_argument('--json',action='store_true')
    d=s.add_parser('doctor',help='檢查 Smart Media / codec 執行環境'); d.add_argument('--json',action='store_true')
    return p

def main(argv=None):
    args=build_parser().parse_args(argv)
    try:
        if args.command=='compress':
            r=compress_archive(args.inputs,args.output,format=args.format,profile=args.profile,progress=_progress); saving=100*(1-r.ratio) if r.input_bytes else 0
            print(f'完成：{r.output}\n輸入：{_human_size(r.input_bytes)}\n輸出：{_human_size(r.output_bytes)}\n節省：{saving:.2f}% | codec={r.codec} | {r.elapsed_seconds:.2f}s')
        elif args.command=='extract': print(extract_archive(args.archive,args.output,progress=_progress))
        elif args.command=='list':
            entries=list_archive(args.archive)
            for x in entries: print(f"{'DIR ' if x.is_dir else 'FILE':4} {_human_size(x.size):>12}  {x.name}")
            print(f'共 {len(entries)} 個項目')
        elif args.command=='verify':
            r=verify_archive(args.archive); print(json.dumps(r,ensure_ascii=False,indent=2) if args.json else ('驗證通過' if r.get('ok') else '驗證失敗')+'\n'+'\n'.join(f'{k}: {v}' for k,v in r.items() if k!='ok')); return 0 if r.get('ok') else 2
        elif args.command=='doctor':
            r=doctor_report(); print(json.dumps(r,ensure_ascii=False,indent=2) if args.json else '\n'.join(f'{k}: {v}' for k,v in r.items())); return 0
    except (RayPackError,OSError,ValueError,RuntimeError) as e: print(f'錯誤：{e}',file=sys.stderr); return 1
    return 0
if __name__=='__main__': raise SystemExit(main())
