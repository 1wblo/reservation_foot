"""Gestion de la connexion a PostgreSQL (pool de connexions psycopg2)."""
import os
from contextlib import contextmanager

import psycopg2
import psycopg2.extras
from psycopg2.pool import ThreadedConnectionPool

_pool: ThreadedConnectionPool | None = None


def get_pool() -> ThreadedConnectionPool:
    """Cree le pool de connexions au premier appel.

    Pool "threaded" : FastAPI execute les endpoints synchrones dans un
    pool de threads, donc plusieurs requetes empruntent des connexions
    en meme temps.

    Les variables d'environnement sont lues ici (pas au chargement du
    module) pour que les tests puissent pointer vers une base differente
    en definissant DB_NAME/DB_HOST/... avant le premier appel.

    Returns:
        Le pool de connexions partage par toute l'application.
    """
    global _pool
    if _pool is None:
        _pool = ThreadedConnectionPool(
            minconn=1,
            maxconn=10,
            host=os.environ.get("DB_HOST", "localhost"),
            port=os.environ.get("DB_PORT", "5432"),
            dbname=os.environ.get("DB_NAME", "terrain_foot"),
            user=os.environ.get("DB_USER", "postgres"),
            password=os.environ.get("DB_PASSWORD", "postgres"),
        )
    return _pool


def reset_pool() -> None:
    """Ferme et oublie le pool courant (utile entre des runs de tests)."""
    global _pool
    if _pool is not None:
        _pool.closeall()
        _pool = None


@contextmanager
def get_connection():
    """Fournit une connexion issue du pool, et la remet au pool a la fin.

    Yields:
        Une connexion psycopg2 ouverte. Elle est rendue au pool a la sortie
        du bloc ``with``, meme si une exception a ete levee.
    """
    pool = get_pool()
    conn = pool.getconn()
    try:
        yield conn
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit: bool = False):
    """Fournit un curseur (dict cursor) sur une connexion du pool.

    Fait un commit si commit=True et qu'aucune exception n'a ete levee,
    sinon fait un rollback pour ne jamais laisser une transaction a moitie
    appliquee.

    Args:
        commit: True pour valider la transaction a la sortie du bloc (a
            utiliser pour les ecritures). False pour une simple lecture.

    Yields:
        Un curseur dont chaque ligne est un dictionnaire {colonne: valeur}.
    """
    with get_connection() as conn:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
