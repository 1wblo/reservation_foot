"""Tests des endpoints clients / terrains."""


def test_lister_terrains_seed(client):
    resp = client.get("/terrains")
    assert resp.status_code == 200
    noms = {t["nom"] for t in resp.json()}
    assert {"Terrain A", "Terrain B", "Terrain C"} <= noms


def test_creer_client(client):
    payload = {"nom": "Gagnon", "prenom": "Eve", "telephone": "514-555-9999", "courriel": "eve@example.com"}
    resp = client.post("/clients", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["nom"] == "Gagnon"
    assert body["id"] is not None


def test_courriel_en_double_rejete(client):
    payload = {"nom": "Gagnon", "prenom": "Eve", "courriel": "eve@example.com"}
    assert client.post("/clients", json=payload).status_code == 201

    resp = client.post("/clients", json={"nom": "Autre", "prenom": "Personne", "courriel": "eve@example.com"})
    assert resp.status_code == 409
    assert "courriel" in resp.json()["detail"]


def test_clients_sans_courriel_ne_sont_pas_des_doublons(client):
    for prenom in ("Sam", "Max"):
        resp = client.post("/clients", json={"nom": "Roy", "prenom": prenom})
        assert resp.status_code == 201


def test_terrains_incluent_leurs_services(client):
    terrains = {t["nom"]: t for t in client.get("/terrains").json()}
    assert [s["code"] for s in terrains["Terrain A"]["services"]] == ["E", "V"]
    assert [s["code"] for s in terrains["Terrain B"]["services"]] == ["A", "E", "V"]
    arbitre = terrains["Terrain B"]["services"][0]
    assert arbitre == {"code": "A", "nom": "Arbitre", "prix": 25.0}


def test_lister_clients_inclut_les_nouveaux(client):
    client.post("/clients", json={"nom": "Roy", "prenom": "Sam", "telephone": None, "courriel": None})
    resp = client.get("/clients")
    assert resp.status_code == 200
    noms = [c["nom"] for c in resp.json()]
    assert "Roy" in noms


def test_occupation_terrains_vide_au_depart(client):
    resp = client.get("/terrains/occupation")
    assert resp.status_code == 200
    assert all(t["heures_reservees"] == 0 for t in resp.json())


def test_occupation_apres_reservation(client):
    from datetime import datetime, timedelta, timezone

    debut = datetime(2026, 11, 5, 10, 0, tzinfo=timezone.utc)
    fin = debut + timedelta(hours=2)
    client.post(
        "/reservations",
        json={
            "terrain_id": 1,
            "client_id": 1,
            "debut": debut.isoformat(),
            "fin": fin.isoformat(),
            "nb_joueurs": 8,
            "equipements": [],
        },
    )
    resp = client.get("/terrains/occupation")
    terrain_a = next(t for t in resp.json() if t["nom"] == "Terrain A")
    assert terrain_a["heures_reservees"] == 2.0
