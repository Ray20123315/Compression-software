from raypack.cli import main

def test_cli_version(capsys):
    try: main(['--version'])
    except SystemExit as e: assert e.code==0
    assert 'RayPack 0.0.2' in capsys.readouterr().out
def test_doctor_json(capsys):
    assert main(['doctor','--json'])==0
    assert 'pillow' in capsys.readouterr().out
