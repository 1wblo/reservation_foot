"""API REST pour la reservation de terrains de foot interieur."""
from fastapi import FastAPI, HTTPException, status

from app import crud
from app.schemas import (
    ClientCreate,
    ClientOut,
    OccupationTerrainOut,
    ReservationCreate,
    ReservationOut,
    TerrainOut,
)

app = FastAPI(
    title="Terrain Foot API",
    description="Reservation de terrains de foot interieur (PostgreSQL + FastAPI)",
    version="1.0.0",
)


@app.get("/health", tags=["meta"])
def health():
    """Indique que le service repond.

    Returns:
        {"status": "ok"} tant que l'API est en marche.
    """
    return {"status": "ok"}


# ---------------------------------------------------------------- Clients --

@app.post("/clients", response_model=ClientOut, status_code=status.HTTP_201_CREATED, tags=["clients"])
def creer_client(payload: ClientCreate):
    """Cree un client.

    Args:
        payload: Nom, prenom, et eventuellement telephone et courriel.

    Returns:
        Le client cree (201).

    Raises:
        HTTPException: 409 si le courriel est deja utilise par un autre client.
    """
    try:
        return crud.create_client(payload.nom, payload.prenom, payload.telephone, payload.courriel)
    except crud.DuplicateEmailError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@app.get("/clients", response_model=list[ClientOut], tags=["clients"])
def lister_clients():
    """Liste tous les clients.

    Returns:
        Les clients, tries par id.
    """
    return crud.list_clients()


# --------------------------------------------------------------- Terrains --

@app.get("/terrains", response_model=list[TerrainOut], tags=["terrains"])
def lister_terrains():
    """Liste les terrains et les services offerts sur chacun.

    Returns:
        Les terrains, tries par id.
    """
    return crud.list_terrains()


@app.get("/terrains/occupation", response_model=list[OccupationTerrainOut], tags=["terrains"])
def occupation_terrains():
    """Donne le nombre d'heures reservees par terrain.

    Returns:
        Une ligne par terrain ; seules les reservations confirmees comptent.
    """
    return crud.get_occupation_terrains()


# ------------------------------------------------------------ Reservations --

@app.post(
    "/reservations",
    response_model=ReservationOut,
    status_code=status.HTTP_201_CREATED,
    tags=["reservations"],
)
def creer_reservation(payload: ReservationCreate):
    """Reserve un terrain sur un creneau, avec location d'equipement optionnelle.

    Args:
        payload: Terrain, client, debut, fin, nombre de joueurs et
            equipements a louer.

    Returns:
        La reservation creee, avec son prix total (201).

    Raises:
        HTTPException: 409 si le terrain est deja reserve sur ce creneau ou
            si le stock d'un equipement est insuffisant ; 404 si le terrain,
            le client ou un equipement n'existe pas ; 422 si la fin n'est pas
            apres le debut ou si la capacite du terrain est depassee.
    """
    try:
        return crud.create_reservation(
            payload.terrain_id,
            payload.client_id,
            payload.debut,
            payload.fin,
            payload.nb_joueurs,
            [e.model_dump() for e in payload.equipements],
        )
    except (crud.ReservationConflictError, crud.InsufficientStockError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except crud.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@app.get("/reservations", response_model=list[ReservationOut], tags=["reservations"])
def lister_reservations():
    """Liste toutes les reservations, annulees comprises.

    Returns:
        Les reservations, triees par id (sans le prix total).
    """
    return crud.list_reservations()


@app.get("/reservations/{reservation_id}", response_model=ReservationOut, tags=["reservations"])
def obtenir_reservation(reservation_id: int):
    """Retourne le detail d'une reservation.

    Args:
        reservation_id: Identifiant de la reservation.

    Returns:
        La reservation, avec son prix total.

    Raises:
        HTTPException: 404 si la reservation n'existe pas.
    """
    try:
        return crud.get_reservation(reservation_id)
    except crud.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@app.delete("/reservations/{reservation_id}", response_model=ReservationOut, tags=["reservations"])
def annuler_reservation(reservation_id: int):
    """Annule une reservation, ce qui libere son creneau.

    Args:
        reservation_id: Identifiant de la reservation a annuler.

    Returns:
        La reservation, au statut "annulee".

    Raises:
        HTTPException: 404 si la reservation n'existe pas ou est deja annulee.
    """
    try:
        return crud.cancel_reservation(reservation_id)
    except crud.NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
