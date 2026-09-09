from __future__ import annotations
import json, os, subprocess, zipfile
from pathlib import Path
import pytest
from PIL import Image
from raypack.core import RayPackError, compress_archive, extract_archive, verify_archive
from raypack.media import doctor_report

def test_smart_requires_rayz(tmp_path):
    p=tmp_path/'a.txt';p.write_text('x')
    with pytest.raises(RayPackError):compress_archive([p],tmp_path/'a.zip',format='zip',profile='smart')
def test_smart_jpeg_smaller_and_restores_dimensions(tmp_path):
    p=tmp_path/'image.jpg';im=Image.effect_noise((1600,1200),80).convert('RGB');im.save(p,'JPEG',quality=96);exact=tmp_path/'exact.rayz';smart=tmp_path/'smart.rayz';compress_archive([p],exact,format='rayz',profile='ultra');compress_archive([p],smart,format='rayz',profile='smart');assert smart.stat().st_size<exact.stat().st_size;v=verify_archive(smart);assert v['smart_media'];o=tmp_path/'out';extract_archive(smart,o);q=o/'image.jpg';assert q.read_bytes()!=p.read_bytes();assert Image.open(q).size==(1600,1200)
def test_smart_png_restores_dimensions(tmp_path):
    p=tmp_path/'image.png';Image.effect_noise((900,700),64).convert('RGB').save(p,'PNG');a=tmp_path/'a.rayz';compress_archive([p],a,format='rayz',profile='smart');o=tmp_path/'out';extract_archive(a,o);assert Image.open(o/'image.png').size==(900,700)
def test_safe_zip_logical_round_trip(tmp_path):
    p=tmp_path/'data.zip'
    with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('data/config.txt','abcde\n'*5000);z.writestr('data/more.txt','hello\n'*3000)
    a=tmp_path/'a.rayz';compress_archive([p],a,format='rayz',profile='smart');o=tmp_path/'out';extract_archive(a,o)
    with zipfile.ZipFile(o/'data.zip') as z:assert z.read('data/config.txt')==b'abcde\n'*5000
def test_signed_jar_falls_back_exact_bytes(tmp_path):
    p=tmp_path/'signed.jar'
    with zipfile.ZipFile(p,'w',compression=zipfile.ZIP_DEFLATED) as z:z.writestr('META-INF/TEST.SF','sig');z.writestr('payload.txt','abc'*5000)
    before=p.read_bytes();a=tmp_path/'a.rayz';compress_archive([p],a,format='rayz',profile='smart');o=tmp_path/'out';extract_archive(a,o);assert (o/'signed.jar').read_bytes()==before

def _ffmpeg():
    r=doctor_report();return r

def test_smart_mp4_round_trip_dimensions(tmp_path):
    r=_ffmpeg()
    if not (r['video_ffmpeg'] and r['video_ffprobe'] and r['video_mpeg4_encoder']):pytest.skip('video ffmpeg unavailable')
    src=tmp_path/'video.mp4';subprocess.run([r['video_ffmpeg'],'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','testsrc=size=1280x720:rate=12','-t','2','-c:v','mpeg4','-q:v','3',str(src)],check=True);a=tmp_path/'v.rayz';compress_archive([src],a,format='rayz',profile='smart');o=tmp_path/'out';extract_archive(a,o);cp=subprocess.run([r['video_ffprobe'],'-v','error','-select_streams','v:0','-show_entries','stream=width,height','-of','json',str(o/'video.mp4')],capture_output=True,text=True,check=True);s=json.loads(cp.stdout)['streams'][0];assert (s['width'],s['height'])==(1280,720)
def test_smart_mp3_round_trip_sample_rate(tmp_path):
    r=_ffmpeg()
    if not (r['audio_ffmpeg'] and r['audio_ffprobe'] and r['audio_libmp3lame_encoder']):pytest.skip('mp3 encoder unavailable')
    src=tmp_path/'tone.mp3';subprocess.run([r['audio_ffmpeg'],'-hide_banner','-loglevel','error','-y','-f','lavfi','-i','sine=frequency=1000:sample_rate=44100','-t','4','-c:a','libmp3lame','-b:a','320k',str(src)],check=True);a=tmp_path/'a.rayz';compress_archive([src],a,format='rayz',profile='smart');o=tmp_path/'out';extract_archive(a,o);cp=subprocess.run([r['audio_ffprobe'],'-v','error','-select_streams','a:0','-show_entries','stream=sample_rate','-of','json',str(o/'tone.mp3')],capture_output=True,text=True,check=True);assert int(json.loads(cp.stdout)['streams'][0]['sample_rate'])==44100
