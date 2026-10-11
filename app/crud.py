"""Acces aux donnees et logique metier (SQL parametre, pas d'ORM)."""
from datetime import datetime

import psycopg2.errors

from app.database import get_cursor


class ReservationConflictError(Exception):
    """Levee quand une reservation chevauche une reservation existante."""


class NotFoundError(Exception):
    """Levee quand une ressource demandee n'existe pas."""


class DuplicateEmailError(Exception):
    """Levee quand un client existe deja avec le meme courriel."""


class InsufficientStockError(Exception):
    """Levee quand un equipement n'est plus disponible en quantite suffisante."""


# ---------------------------------------------------------------- Clients --

def create_client(nom: str, prenom: str, telephone: str | None, courriel: str | None) -> dict:
    """Enregistre un nouveau client.

    Args:
        nom: Nom de famille.
        prenom: Prenom.
        telephone: Numero de telephone, ou None.
        courriel: Adresse courriel, ou None. Doit etre unique ; plusieurs
            clients peuvent toutefois ne pas en avoir.

    Returns:
        Le client cree, avec son id et sa date d'inscription.

    Raises:
        DuplicateEmailError: Un autre client utilise deja ce courriel.
    """
    with get_cursor(commit=True) as cur:
        try:
            cur.execute(
                """
                INSERT INTO client (nom, prenom, telephone, courriel)
                VALUES (%s, %s, %s, %s)
                RETURNING id, nom, prenom, telephone, courriel, date_inscription
                """,
                (nom, prenom, telephone, courriel),
            )
        except psycopg2.errors.UniqueViolation as exc:
            raise DuplicateEmailError(
                f"Un client existe deja avec le courriel {courriel}"
            ) from exc
        return dict(cur.fetchone())


def list_clients() -> list[dict]:
    """Liste tous les clients.

    Returns:
        Les clients, tries par id.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, nom, prenom, telephone, courriel, date_inscription "
            "FROM client ORDER BY id"
        )
        return [dict(row) for row in cur.fetchall()]


# --------------------------------------------------------------- Terrains --

def list_terrains() -> list[dict]:
    """Liste tous les terrains avec les services qu'ils offrent.

    Returns:
        Les terrains, tries par id. Chaque terrain contient une cle
        "services" : la liste (possiblement vide) de ses services, sous la
        forme {code, nom, prix}.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT t.id, t.nom, t.surface_m2, t.type_code, t.capacite_max,
                   COALESCE(
                       json_agg(
                           json_build_object('code', s.code, 'nom', s.nom, 'prix', s.prix)
                           ORDER BY s.code
                       ) FILTER (WHERE s.code IS NOT NULL),
                       '[]'
                   ) AS services
            FROM terrain t
            LEFT JOIN terrain_service ts ON ts.terrain_id = t.id
            LEFT JOIN service s ON s.code = ts.service_code
            GROUP BY t.id
            ORDER BY t.id
            """
        )
        return [dict(row) for row in cur.fetchall()]


def get_occupation_terrains() -> list[dict]:
    """Calcule le nombre d'heures reservees sur chaque terrain.

    S'appuie sur la vue SQL occupation_terrain, qui ne compte que les
    reservations confirmees.

    Returns:
        Une ligne {id, nom, heures_reservees} par terrain, triee par id.
        Un terrain sans reservation apparait avec 0 heure.
    """
    with get_cursor() as cur:
        cur.execute("SELECT id, nom, heures_reservees FROM occupation_terrain ORDER BY id")
        return [dict(row) for row in cur.fetchall()]


# ------------------------------------------------------------ Reservations --

def create_reservation(
    terrain_id: int,
    client_id: int,
    debut: datetime,
    fin: datetime,
    nb_joueurs: int,
    equipements: list[dict],
) -> dict:
    """Cree une reservation confirmee, avec ses equipements loues.

    Tout se passe dans une seule transaction : si une verification echoue
    (creneau pris, stock insuffisant...), rien n'est enregistre.

    Args:
        terrain_id: Terrain a reserver.
        client_id: Client qui reserve.
        debut: Debut du creneau (inclus).
        fin: Fin du creneau (exclue) : une reservation peut donc commencer
            a l'instant exact ou la precedente se termine.
        nb_joueurs: Nombre de joueurs, limite par la capacite du terrain.
        equipements: Equipements a louer, sous la forme
            [{"equipement_id": ..., "quantite": ...}, ...].

    Returns:
        La reservation creee, avec son prix total (cle "total").

    Raises:
        ValueError: La fin n'est pas apres le debut, ou il y a trop de
            joueurs pour ce terrain.
        NotFoundError: Le terrain, le client ou un equipement n'existe pas.
        ReservationConflictError: Le terrain est deja reserve sur ce creneau.
        InsufficientStockError: Un equipement n'est plus disponible en
            quantite suffisante sur ce creneau.
    """
    if fin <= debut:
        raise ValueError("La date de fin doit etre apres la date de debut")

    with get_cursor(commit=True) as cur:
        # Le verrou sur le terrain met en file les reservations concurrentes
        # d'un meme terrain. C'est la contrainte EXCLUDE qui garantit
        # l'absence de chevauchement ; sans ce verrou, des insertions
        # simultanees en conflit s'attendent mutuellement et Postgres en
        # tue une avec "deadlock detected" au lieu d'un conflit propre.
        cur.execute(
            "SELECT capacite_max FROM terrain WHERE id = %s FOR NO KEY UPDATE",
            (terrain_id,),
        )
        terrain = cur.fetchone()
        if terrain is None:
            raise NotFoundError(f"Terrain {terrain_id} introuvable")
        if nb_joueurs > terrain["capacite_max"]:
            raise ValueError(
                f"Ce terrain accepte au maximum {terrain['capacite_max']} joueurs"
            )

        try:
            cur.execute(
                """
                INSERT INTO reservation (terrain_id, client_id, plage, nb_joueurs)
                VALUES (%s, %s, tstzrange(%s, %s, '[)'), %s)
                RETURNING id, terrain_id, client_id,
                          lower(plage) AS debut, upper(plage) AS fin,
                          nb_joueurs, statut
                """,
                (terrain_id, client_id, debut, fin, nb_joueurs),
            )
        except psycopg2.errors.ExclusionViolation as exc:
            raise ReservationConflictError(
                "Ce terrain est deja reserve sur ce creneau"
            ) from exc
        except psycopg2.errors.ForeignKeyViolation as exc:
            raise NotFoundError(f"Client {client_id} introuvable") from exc

        reservation = dict(cur.fetchone())
        _louer_equipements(cur, reservation["id"], debut, fin, equipements)

        cur.execute(
            "SELECT calculer_total_reservation(%s) AS total", (reservation["id"],)
        )
        reservation["total"] = float(cur.fetchone()["total"])

    return reservation


def _louer_equipements(cur, reservation_id: int, debut: datetime, fin: datetime, equipements: list[dict]) -> None:
    """Rattache les equipements a la reservation, en verifiant le stock.

    Le stock est un nombre d'unites louables en meme temps : on compte donc
    ce qui est deja loue par les reservations confirmees qui chevauchent le
    creneau, pas tout ce qui a ete loue depuis toujours.

    Args:
        cur: Curseur de la transaction qui vient de creer la reservation.
        reservation_id: Reservation a laquelle rattacher les equipements.
        debut: Debut du creneau de la reservation.
        fin: Fin du creneau de la reservation.
        equipements: Equipements demandes ([{"equipement_id", "quantite"}]).
            Un meme equipement cite plusieurs fois voit ses quantites
            additionnees.

    Raises:
        NotFoundError: Un equipement demande n'existe pas.
        InsufficientStockError: Le stock restant sur ce creneau ne couvre
            pas la quantite demandee.
    """
    quantites: dict[int, int] = {}
    for item in equipements:
        quantites[item["equipement_id"]] = quantites.get(item["equipement_id"], 0) + item["quantite"]

    # Verrouille chaque equipement (toujours dans le meme ordre, pour eviter
    # les interblocages) : deux reservations simultanees ne peuvent pas
    # prendre chacune les dernieres unites.
    for equipement_id in sorted(quantites):
        cur.execute(
            "SELECT nom, stock FROM equipement WHERE id = %s FOR NO KEY UPDATE",
            (equipement_id,),
        )
        equipement = cur.fetchone()
        if equipement is None:
            raise NotFoundError(f"Equipement {equipement_id} introuvable")

        cur.execute(
            """
            SELECT COALESCE(SUM(re.quantite), 0) AS deja_loue
            FROM reservation_equipement re
            JOIN reservation r ON r.id = re.reservation_id
            WHERE re.equipement_id = %s
              AND r.statut = 'confirmee'
              AND r.plage && tstzrange(%s, %s, '[)')
            """,
            (equipement_id, debut, fin),
        )
        disponible = equipement["stock"] - cur.fetchone()["deja_loue"]
        if quantites[equipement_id] > disponible:
            raise InsufficientStockError(
                f"Stock insuffisant pour {equipement['nom']} : "
                f"{disponible} disponible(s) sur ce creneau"
            )

        cur.execute(
            """
            INSERT INTO reservation_equipement (reservation_id, equipement_id, quantite)
            VALUES (%s, %s, %s)
            """,
            (reservation_id, equipement_id, quantites[equipement_id]),
        )


def get_reservation(reservation_id: int) -> dict:
    """Retrouve une reservation et calcule son prix total.

    Args:
        reservation_id: Identifiant de la reservation.

    Returns:
        La reservation, avec son prix total (cle "total").

    Raises:
        NotFoundError: Aucune reservation ne porte cet identifiant.
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, terrain_id, client_id,
                   lower(plage) AS debut, upper(plage) AS fin,
                   nb_joueurs, statut
            FROM reservation
            WHERE id = %s
            """,
            (reservation_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise NotFoundError(f"Reservation {reservation_id} introuvable")
        reservation = dict(row)

        cur.execute(
            "SELECT calculer_total_reservation(%s) AS total", (reservation_id,)
        )
        reservation["total"] = float(cur.fetchone()["total"])
        return reservation


def list_reservations() -> list[dict]:
    """Liste toutes les reservations, annulees comprises.

    Returns:
        Les reservations, triees par id. Le prix total n'est pas calcule
        ici (voir get_reservation).
    """
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, terrain_id, client_id,
                   lower(plage) AS debut, upper(plage) AS fin,
                   nb_joueurs, statut
            FROM reservation
            ORDER BY id
            """
        )
        return [dict(row) for row in cur.fetchall()]


def cancel_reservation(reservation_id: int) -> dict:
    """Annule une reservation confirmee.

    La reservation n'est pas supprimee : elle passe au statut "annulee",
    ce qui libere son creneau et ses equipements tout en gardant
    l'historique.

    Args:
        reservation_id: Identifiant de la reservation a annuler.

    Returns:
        La reservation, avec son nouveau statut.

    Raises:
        NotFoundError: La reservation n'existe pas, ou est deja annulee.
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE reservation SET statut = 'annulee'
            WHERE id = %s AND statut = 'confirmee'
            RETURNING id, terrain_id, client_id,
                      lower(plage) AS debut, upper(plage) AS fin,
                      nb_joueurs, statut
            """,
            (reservation_id,),
        )
        row = cur.fetchone()
        if row is None:
            raise NotFoundError(
                f"Reservation {reservation_id} introuvable ou deja annulee"
            )
        return dict(row)
