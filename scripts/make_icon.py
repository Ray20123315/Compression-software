from __future__ import annotations
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def main():
    p=argparse.ArgumentParser(); p.add_argument('--out',required=True); p.add_argument('--png'); a=p.parse_args(); out=Path(a.out); out.parent.mkdir(parents=True,exist_ok=True)
    im=Image.new('RGBA',(256,256),(31,42,68,255)); d=ImageDraw.Draw(im); d.rounded_rectangle((28,36,228,220),radius=28,fill=(63,92,155,255)); d.rectangle((55,70,201,92),fill=(233,239,255,255)); d.rectangle((55,112,201,134),fill=(233,239,255,255)); d.rectangle((55,154,170,176),fill=(233,239,255,255)); d.polygon([(180,146),(218,166),(180,186)],fill=(255,208,92,255))
    im.save(out,format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])
    if a.png: Path(a.png).parent.mkdir(parents=True,exist_ok=True); im.save(a.png)
if __name__=='__main__': main()
