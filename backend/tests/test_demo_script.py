"""scripts/demo.py: prints only unless --save is given (the README quickstart must leave the git tree clean)."""

from scripts import demo


def test_demo_writes_preview_data_only_with_save(monkeypatch, tmp_path):
    out = tmp_path / "preview_data.json"
    monkeypatch.setattr(demo, "OUT", out)
    demo.main([])
    assert not out.exists()
    demo.main(["--save"])
    assert out.exists() and '"cases"' in out.read_text()
