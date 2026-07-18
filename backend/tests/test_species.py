from backend.tests.conftest import IDS


def test_list_species(client, owner_headers):
    res = client.get("/species", headers=owner_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data) >= 3
    cardinal = next(s for s in data if s["common_name"] == "Test Cardinal")
    assert cardinal["palette"] == ["#b8412c", "#5a1810", "#e5b89c"]
    assert cardinal["silhouette"] == "songbird"
    assert cardinal["genus"] == "Cardinalis"


def test_get_one_species(client, owner_headers):
    res = client.get(f"/species/{IDS['spA_id']}", headers=owner_headers)
    assert res.status_code == 200
    assert res.json()["common_name"] == "Test Cardinal"


def test_create_species(client, owner_headers):
    payload = {
        "common_name": "Made Up Finch", "genus": "Fakeus", "species_name": "inventus",
        "order_name": "Passeriformes", "wiki_url": None,
        "palette": ["#111111", "#222222", "#333333"], "silhouette": "finch", "note": "n",
    }
    res = client.post("/species", json=payload, headers=owner_headers)
    assert res.status_code == 201
    body = res.json()
    assert body["palette"] == ["#111111", "#222222", "#333333"]
    assert body["silhouette"] == "finch"
