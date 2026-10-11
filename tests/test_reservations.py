"""Tests de la logique de reservation : chevauchement, prix, annulation."""
import threading
from datetime import datetime, timedelta, timezone

from app import crud

BASE = datetime(2026, 11, 2, 18, 0, tzinfo=timezone.utc)  # un lundi 18h


def _reservation_payload(terrain_id=1, client_id=1, start=BASE, hours=1, nb_joueurs=10, equipements=None):
    return {
        "terrain_id": terrain_id,
        "client_id": client_id,
        "debut": start.isoformat(),
        "fin": (start + timedelta(hours=hours)).isoformat(),
        "nb_joueurs": nb_joueurs,
        "equipements": equipements or [],
    }


def test_creer_reservation_simple(client):
    resp = client.post("/reservations", json=_reservation_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert body["statut"] == "confirmee"
    assert body["total"] == 60.00  # Terrain A (type '5') = 60$/h, 1h


def test_double_reservation_meme_creneau_rejetee(client):
    first = client.post("/reservations", json=_reservation_payload())
    assert first.status_code == 201

    # Meme terrain, creneau qui chevauche partiellement
    overlap_start = BASE + timedelta(minutes=30)
    second = client.post("/reservations", json=_reservation_payload(start=overlap_start))
    assert second.status_code == 409
    assert "deja reserve" in second.json()["detail"]


def test_creneaux_adjacents_acceptes(client):
    """Deux reservations qui se suivent sans se chevaucher doivent passer."""
    first = client.post("/reservations", json=_reservation_payload(start=BASE, hours=1))
    assert first.status_code == 201

    second_start = BASE + timedelta(hours=1)  # commence pile quand la 1re finit
    second = client.post("/reservations", json=_reservation_payload(start=second_start, hours=1))
    assert second.status_code == 201


def test_meme_creneau_terrain_different_accepte(client):
    first = client.post("/reservations", json=_reservation_payload(terrain_id=1))
    assert first.status_code == 201

    second = client.post("/reservations", json=_reservation_payload(terrain_id=2))
    assert second.status_code == 201


def test_annulation_libere_le_creneau(client):
    created = client.post("/reservations", json=_reservation_payload()).json()

    cancel = client.delete(f"/reservations/{created['id']}")
    assert cancel.status_code == 200
    assert cancel.json()["statut"] == "annulee"

    # Le meme creneau redevient disponible une fois la reservation annulee
    again = client.post("/reservations", json=_reservation_payload())
    assert again.status_code == 201


def test_total_avec_equipements(client):
    payload = _reservation_payload(
        equipements=[{"equipement_id": 1, "quantite": 2}]  # 2 ballons a 5$
    )
    resp = client.post("/reservations", json=payload)
    assert resp.status_code == 201
    # 60$ (terrain, 1h) + 2 x 5$ (ballons) = 70$
    assert resp.json()["total"] == 70.00


def test_fin_avant_debut_rejetee(client):
    resp = client.post(
        "/reservations",
        json=_reservation_payload(start=BASE, hours=-1),
    )
    assert resp.status_code == 422


def test_reservation_terrain_inexistant(client):
    resp = client.post("/reservations", json=_reservation_payload(terrain_id=9999))
    assert resp.status_code == 404


def test_trop_de_joueurs_rejete(client):
    # Terrain A : capacite_max = 10
    resp = client.post("/reservations", json=_reservation_payload(nb_joueurs=11))
    assert resp.status_code == 422
    assert "10 joueurs" in resp.json()["detail"]


def test_client_inexistant(client):
    resp = client.post("/reservations", json=_reservation_payload(client_id=9999))
    assert resp.status_code == 404


# ------------------------------------------------------------ Equipements --

def test_equipement_inexistant(client):
    payload = _reservation_payload(equipements=[{"equipement_id": 9999, "quantite": 1}])
    resp = client.post("/reservations", json=payload)
    assert resp.status_code == 404
    # La reservation ne doit pas avoir ete creee a moitie
    assert client.get("/reservations").json() == []


def test_stock_insuffisant_rejete(client):
    # Dossards : stock = 8
    payload = _reservation_payload(equipements=[{"equipement_id": 2, "quantite": 9}])
    resp = client.post("/reservations", json=payload)
    assert resp.status_code == 409
    assert "Stock insuffisant" in resp.json()["detail"]
    assert client.get("/reservations").json() == []


def test_stock_partage_entre_reservations_simultanees(client):
    """Le stock est compte par creneau : deux terrains reserves en meme
    temps se partagent les memes dossards."""
    first = client.post(
        "/reservations",
        json=_reservation_payload(terrain_id=1, equipements=[{"equipement_id": 2, "quantite": 6}]),
    )
    assert first.status_code == 201

    # Meme creneau, autre terrain : il ne reste que 2 jeux de dossards
    trop = client.post(
        "/reservations",
        json=_reservation_payload(terrain_id=2, equipements=[{"equipement_id": 2, "quantite": 3}]),
    )
    assert trop.status_code == 409

    assez = client.post(
        "/reservations",
        json=_reservation_payload(terrain_id=2, equipements=[{"equipement_id": 2, "quantite": 2}]),
    )
    assert assez.status_code == 201

    # Un autre creneau retrouve tout le stock
    plus_tard = client.post(
        "/reservations",
        json=_reservation_payload(
            start=BASE + timedelta(hours=3),
            equipements=[{"equipement_id": 2, "quantite": 8}],
        ),
    )
    assert plus_tard.status_code == 201


def test_annulation_libere_le_stock(client):
    created = client.post(
        "/reservations",
        json=_reservation_payload(terrain_id=1, equipements=[{"equipement_id": 2, "quantite": 8}]),
    ).json()
    client.delete(f"/reservations/{created['id']}")

    resp = client.post(
        "/reservations",
        json=_reservation_payload(terrain_id=2, equipements=[{"equipement_id": 2, "quantite": 8}]),
    )
    assert resp.status_code == 201


def test_equipement_en_double_additionne(client):
    payload = _reservation_payload(
        equipements=[
            {"equipement_id": 1, "quantite": 1},
            {"equipement_id": 1, "quantite": 2},
        ]
    )
    resp = client.post("/reservations", json=payload)
    assert resp.status_code == 201
    assert resp.json()["total"] == 75.00  # 60$ + 3 ballons a 5$


# ------------------------------------------------------------- Concurrence --

def _lancer_en_parallele(nb_threads, action):
    """Execute action(i) dans nb_threads threads qui demarrent en meme temps.

    Retourne la liste des resultats : la valeur retournee, ou l'exception levee.
    """
    depart = threading.Barrier(nb_threads)
    resultats = [None] * nb_threads

    def travail(i):
        depart.wait()
        try:
            resultats[i] = action(i)
        except Exception as exc:  # on veut voir toutes les erreurs, pas juste les attendues
            resultats[i] = exc

    threads = [threading.Thread(target=travail, args=(i,)) for i in range(nb_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    return resultats


def test_reservations_concurrentes_une_seule_passe():
    """8 requetes simultanees pour le meme creneau : exactement une reussit,
    les autres recoivent une erreur de conflit (pas de 500, pas de doublon)."""
    nb = 8
    resultats = _lancer_en_parallele(
        nb,
        lambda i: crud.create_reservation(1, 1, BASE, BASE + timedelta(hours=1), 10, []),
    )

    reussies = [r for r in resultats if isinstance(r, dict)]
    conflits = [r for r in resultats if isinstance(r, crud.ReservationConflictError)]
    assert len(reussies) == 1, resultats
    assert len(conflits) == nb - 1, resultats
    assert len(crud.list_reservations()) == 1


def test_stock_concurrent_jamais_depasse():
    """Les 3 terrains sont reserves en meme temps sur le meme creneau, avec
    3 jeux de dossards chacun (stock = 8) : le total loue ne doit jamais
    depasser le stock."""
    nb = 3  # un par terrain
    resultats = _lancer_en_parallele(
        nb,
        lambda i: crud.create_reservation(
            i + 1, 1, BASE, BASE + timedelta(hours=1), 10,
            [{"equipement_id": 2, "quantite": 3}],
        ),
    )

    reussies = [r for r in resultats if isinstance(r, dict)]
    refusees = [r for r in resultats if isinstance(r, crud.InsufficientStockError)]
    assert len(reussies) == 2, resultats  # 2 x 3 = 6 <= 8, la 3e depasserait
    assert len(refusees) == 1, resultats
