import json

import pytest

import download_data as dd

RESOURCES = [
    {"name": "Dictionnaire de données", "format": "CSV", "url": "https://donnees.montreal.ca/dico.csv"},
    {"name": "Actes criminels", "format": "CSV", "url": "https://donnees.montreal.ca/actes-criminels.csv"},
    {"name": "Limites (NAD83 / MTM zone 8)", "format": "GeoJSON", "url": "https://donnees.montreal.ca/mtm.geojson"},
    {"name": "Limites (WGS 84)", "format": "GeoJSON", "url": "https://donnees.montreal.ca/wgs.geojson"},
]


def test_pick_resource_uses_format_and_name_filters():
    assert dd.pick_resource(RESOURCES, {"CSV"}, "", "dictionnaire")["name"] == "Actes criminels"
    assert dd.pick_resource(RESOURCES, {"GEOJSON"}, "WGS")["url"].endswith("wgs.geojson")


def test_pick_resource_fails_clearly_when_nothing_matches():
    with pytest.raises(LookupError):
        dd.pick_resource(RESOURCES, {"SHP"})


def test_download_refuses_other_hosts():
    with pytest.raises(ValueError):
        dd._check_url("http://donnees.montreal.ca/x.csv")
    with pytest.raises(ValueError):
        dd._check_url("https://example.com/x.csv")
    dd._check_url("https://donnees.montreal.ca/x.csv")


def test_main_downloads_both_files_and_records_their_version(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dd, "DATA_DIR", tmp_path / "data")
    monkeypatch.setitem(dd.DATASETS, "crimes", dd.DATASETS["crimes"][:4] + (tmp_path / "data" / "a.csv",))
    monkeypatch.setitem(dd.DATASETS, "boundary", dd.DATASETS["boundary"][:4] + (tmp_path / "data" / "b.geojson",))

    saved = []

    def fake_fetch(url):
        return {"success": True, "result": {"resources": RESOURCES}}

    def fake_save(url, target):
        saved.append(url)
        return 123, "abc"

    assert dd.main([], fetch=fake_fetch, save=fake_save) == 0
    assert saved == ["https://donnees.montreal.ca/actes-criminels.csv", "https://donnees.montreal.ca/wgs.geojson"]
    info = json.loads((tmp_path / "data" / "DOWNLOAD_INFO.json").read_text())
    assert len(info) == 2 and all(v["sha256"] == "abc" for v in info.values())
