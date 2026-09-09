from __future__ import annotations
import io, os, tarfile, zipfile
from pathlib import Path
import pytest
from raypack.core import ArchiveSecurityError, compress_archive, extract_archive, list_archive, verify_archive

def _fixture_tree(root: Path):
    (root/'config').mkdir(parents=True);(root/'scripts').mkdir();(root/'mods').mkdir();(root/'config'/'settings.toml').write_text('feature=true\n'*500);(root/'scripts'/'startup.mcfunction').write_text('say RayPack\n'*600);(root/'readme.txt').write_text('minecraft modpack test\n'*400)
    with zipfile.ZipFile(root/'mods'/'example.jar','w',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:z.writestr('META-INF/MANIFEST.MF','Manifest-Version: 1.0\n');z.writestr('data.bin',os.urandom(4096))
def _tree_bytes(root):return {p.relative_to(root).as_posix():p.read_bytes() for p in root.rglob('*') if p.is_file()}
@pytest.mark.parametrize('profile',['balanced','ultra','minecraft','autobest'])
def test_rayz_round_trip(tmp_path,profile):
    s=tmp_path/'pack';s.mkdir();_fixture_tree(s);before=_tree_bytes(s);a=tmp_path/f'{profile}.rayz';compress_archive([s],a,format='rayz',profile=profile);assert verify_archive(a)['ok'];assert list_archive(a);o=tmp_path/'out';extract_archive(a,o);assert _tree_bytes(o/'pack')==before
def test_zip_round_trip(tmp_path):
    s=tmp_path/'data';s.mkdir();_fixture_tree(s);a=tmp_path/'data.zip';compress_archive([s],a,format='zip',profile='balanced');o=tmp_path/'out';extract_archive(a,o);assert _tree_bytes(o/'data')==_tree_bytes(s)
def test_tar_xz_round_trip(tmp_path):
    s=tmp_path/'data';s.mkdir();_fixture_tree(s);a=tmp_path/'data.tar.xz';compress_archive([s],a,format='tar.xz',profile='ultra');o=tmp_path/'out';extract_archive(a,o);assert _tree_bytes(o/'data')==_tree_bytes(s)
def test_rejects_zip_path_traversal(tmp_path):
    a=tmp_path/'evil.zip'
    with zipfile.ZipFile(a,'w') as z:z.writestr('../outside.txt',b'owned')
    with pytest.raises(ArchiveSecurityError):extract_archive(a,tmp_path/'out')
def test_rejects_tar_path_traversal(tmp_path):
    a=tmp_path/'evil.tar'
    with tarfile.open(a,'w') as t:
        i=tarfile.TarInfo('../outside.txt');d=b'owned';i.size=len(d);t.addfile(i,io.BytesIO(d))
    with pytest.raises(ArchiveSecurityError):extract_archive(a,tmp_path/'out')
def test_fast_zstd_round_trip_when_available(tmp_path):
    pytest.importorskip('zstandard');s=tmp_path/'fast.txt';s.write_text('fast-zstd\n'*2000);a=tmp_path/'fast.rayz';compress_archive([s],a,format='rayz',profile='fast');o=tmp_path/'out';extract_archive(a,o);assert (o/'fast.txt').read_bytes()==s.read_bytes()
