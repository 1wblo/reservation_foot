"""Modeles Pydantic (validation des requetes/reponses de l'API)."""
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class ClientCreate(BaseModel):
    """Donnees envoyees pour creer un client."""

    nom: str
    prenom: str
    telephone: Optional[str] = None
    courriel: Optional[EmailStr] = None


class ClientOut(ClientCreate):
    """Client tel que retourne par l'API (avec les champs generes par la base)."""

    id: int
    date_inscription: date


class ServiceOut(BaseModel):
    """Service offert sur un terrain (vestiaire, eclairage, arbitre...)."""

    code: str
    nom: str
    prix: float


class TerrainOut(BaseModel):
    """Terrain tel que retourne par l'API.

    type_code renvoie au type de terrain ('5', '7' ou 'O' pour 11 contre 11),
    qui determine le prix a l'heure.
    """

    id: int
    nom: str
    surface_m2: float
    type_code: str
    capacite_max: int
    services: list[ServiceOut] = []


class EquipementReservation(BaseModel):
    """Equipement a louer avec une reservation, et en quelle quantite."""

    equipement_id: int
    quantite: int = Field(gt=0)


class ReservationCreate(BaseModel):
    """Donnees envoyees pour creer une reservation.

    Le creneau va de debut (inclus) a fin (exclue).
    """

    terrain_id: int
    client_id: int
    debut: datetime
    fin: datetime
    nb_joueurs: int = Field(gt=0)
    equipements: list[EquipementReservation] = []


class ReservationOut(BaseModel):
    """Reservation telle que retournee par l'API.

    total vaut None dans les listes : le prix n'est calcule que pour une
    reservation consultee ou creee individuellement.
    """

    id: int
    terrain_id: int
    client_id: int
    debut: datetime
    fin: datetime
    nb_joueurs: int
    statut: str
    total: Optional[float] = None


class OccupationTerrainOut(BaseModel):
    """Nombre d'heures reservees (reservations confirmees) sur un terrain."""

    id: int
    nom: str
    heures_reservees: float
