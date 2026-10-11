"""Client CLI interactif pour l'API Terrain Foot (menu texte en console).

Usage : python demo_cli.py [url_de_base]   (defaut : http://localhost:8000)
"""
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime

BASE_URL = "http://localhost:8000"
TIMEOUT_S = 10


class ApiError(Exception):
    """Levee quand l'API repond avec un code d'erreur HTTP."""

    def __init__(self, status: int, detail: str):
        super().__init__(detail)
        self.status = status
        self.detail = detail


class ApiInjoignableError(Exception):
    """Levee quand l'API ne repond pas (serveur arrete, mauvaise URL...)."""


# ------------------------------------------------------------------ HTTP --

def appeler_api(methode: str, chemin: str, payload: dict | None = None):
    """Envoie une requete a l'API et retourne le JSON decode."""
    corps = json.dumps(payload).encode("utf-8") if payload is not None else None
    requete = urllib.request.Request(
        BASE_URL + chemin,
        data=corps,
        method=methode,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(requete, timeout=TIMEOUT_S) as reponse:
            return json.loads(reponse.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, extraire_detail(exc.read())) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raison = getattr(exc, "reason", exc)
        raise ApiInjoignableError(str(raison)) from exc


def extraire_detail(corps: bytes) -> str:
    """Extrait un message lisible du corps d'une reponse d'erreur FastAPI."""
    texte = corps.decode("utf-8", errors="replace").strip()
    try:
        detail = json.loads(texte)["detail"]
    except (ValueError, KeyError, TypeError):
        return texte or "(aucun détail)"

    # Erreurs de validation Pydantic : liste de {loc, msg, ...}
    if isinstance(detail, list):
        lignes = []
        for erreur in detail:
            champ = ".".join(str(p) for p in erreur.get("loc", []) if p != "body")
            lignes.append(f"{champ} : {erreur.get('msg', '')}" if champ else erreur.get("msg", ""))
        return " ; ".join(lignes)
    return str(detail)


# ---------------------------------------------------------------- Saisie --

def demander_texte(libelle: str, obligatoire: bool = True) -> str | None:
    while True:
        valeur = input(f"  {libelle} : ").strip()
        if valeur:
            return valeur
        if not obligatoire:
            return None
        print("  ! Ce champ est obligatoire.")


def demander_entier(libelle: str) -> int:
    while True:
        valeur = input(f"  {libelle} : ").strip()
        try:
            nombre = int(valeur)
        except ValueError:
            print("  ! Veuillez entrer un nombre entier.")
            continue
        if nombre > 0:
            return nombre
        print("  ! Le nombre doit être supérieur à 0.")


def demander_date(libelle: str) -> str:
    """Demande une date/heure et la retourne au format ISO 8601."""
    while True:
        valeur = input(f"  {libelle} (AAAA-MM-JJ HH:MM) : ").strip()
        try:
            return datetime.fromisoformat(valeur).isoformat()
        except ValueError:
            print("  ! Format invalide. Exemple : 2026-12-01 18:00")


# ------------------------------------------------------------- Affichage --

def afficher_tableau(entetes: list[str], lignes: list[list]) -> None:
    lignes = [["-" if cellule is None else str(cellule) for cellule in ligne] for ligne in lignes]
    largeurs = [
        max(len(entete), *(len(ligne[i]) for ligne in lignes))
        for i, entete in enumerate(entetes)
    ]
    print("  " + "  ".join(e.ljust(l) for e, l in zip(entetes, largeurs)))
    print("  " + "  ".join("-" * l for l in largeurs))
    for ligne in lignes:
        print("  " + "  ".join(c.ljust(l) for c, l in zip(ligne, largeurs)))


def formater_date(valeur: str) -> str:
    return datetime.fromisoformat(valeur).strftime("%Y-%m-%d %H:%M")


# --------------------------------------------------------------- Actions --

def lister_terrains() -> None:
    terrains = appeler_api("GET", "/terrains")
    if not terrains:
        print("  Aucun terrain.")
        return
    afficher_tableau(
        ["ID", "Nom", "Surface (m2)", "Type", "Capacité max", "Services"],
        [
            [
                t["id"], t["nom"], t["surface_m2"], t["type_code"], t["capacite_max"],
                ", ".join(s["nom"] for s in t.get("services", [])) or None,
            ]
            for t in terrains
        ],
    )


def creer_client() -> None:
    payload = {
        "nom": demander_texte("Nom"),
        "prenom": demander_texte("Prénom"),
        "courriel": demander_texte("Courriel (optionnel)", obligatoire=False),
    }
    try:
        client = appeler_api("POST", "/clients", payload)
    except ApiError as exc:
        if exc.status == 409:
            print(f"  ✗ Client non créé : {exc.detail}")
        elif exc.status == 422:
            print(f"  ✗ Données invalides : {exc.detail}")
        else:
            raise
        return
    print(f"  ✓ Client créé : {client['prenom']} {client['nom']} (id {client['id']})")


def voir_occupation() -> None:
    occupation = appeler_api("GET", "/terrains/occupation")
    if not occupation:
        print("  Aucun terrain.")
        return
    afficher_tableau(
        ["ID", "Nom", "Heures réservées"],
        [[o["id"], o["nom"], f"{o['heures_reservees']:.1f}"] for o in occupation],
    )


def faire_reservation() -> None:
    payload = {
        "terrain_id": demander_entier("ID du terrain"),
        "client_id": demander_entier("ID du client"),
        "debut": demander_date("Début"),
        "fin": demander_date("Fin"),
        "nb_joueurs": demander_entier("Nombre de joueurs"),
    }
    try:
        reservation = appeler_api("POST", "/reservations", payload)
    except ApiError as exc:
        if exc.status == 409:
            print("  ✗ RÉSERVATION REFUSÉE : chevauchement avec une réservation existante.")
            print(f"    ({exc.detail})")
        elif exc.status == 404:
            print(f"  ✗ Réservation impossible : {exc.detail}")
        elif exc.status == 422:
            print(f"  ✗ Données invalides : {exc.detail}")
        else:
            raise
        return
    print(
        f"  ✓ Réservation {reservation['id']} confirmée : terrain {reservation['terrain_id']}, "
        f"{formater_date(reservation['debut'])} -> {formater_date(reservation['fin'])}, "
        f"total {reservation['total']:.2f} $"
    )


def lister_reservations() -> None:
    reservations = appeler_api("GET", "/reservations")
    if not reservations:
        print("  Aucune réservation.")
        return
    afficher_tableau(
        ["ID", "Terrain", "Client", "Début", "Fin", "Joueurs", "Statut"],
        [
            [
                r["id"], r["terrain_id"], r["client_id"],
                formater_date(r["debut"]), formater_date(r["fin"]),
                r["nb_joueurs"], r["statut"],
            ]
            for r in reservations
        ],
    )


def annuler_reservation() -> None:
    reservation_id = demander_entier("ID de la réservation à annuler")
    try:
        reservation = appeler_api("DELETE", f"/reservations/{reservation_id}")
    except ApiError as exc:
        if exc.status == 404:
            print(f"  ✗ Annulation impossible : {exc.detail}")
            return
        raise
    print(f"  ✓ Réservation {reservation['id']} annulée (statut : {reservation['statut']}).")


# ------------------------------------------------------------------ Menu --

ACTIONS = {
    "1": ("Lister les terrains", lister_terrains),
    "2": ("Créer un client", creer_client),
    "3": ("Voir l'occupation des terrains", voir_occupation),
    "4": ("Faire une réservation", faire_reservation),
    "5": ("Lister les réservations", lister_reservations),
    "6": ("Annuler une réservation", annuler_reservation),
}


def afficher_menu() -> None:
    print("\n=== Terrain Foot ===")
    for touche, (libelle, _) in ACTIONS.items():
        print(f"{touche}. {libelle}")
    print("0. Quitter")


def main() -> None:
    global BASE_URL
    if len(sys.argv) > 1:
        BASE_URL = sys.argv[1].rstrip("/")

    while True:
        afficher_menu()
        try:
            choix = input("Votre choix : ").strip()
            if choix == "0":
                break
            if choix not in ACTIONS:
                print("  ! Choix invalide, entrez un numéro du menu.")
                continue
            print()
            ACTIONS[choix][1]()
        except ApiInjoignableError as exc:
            print(f"  ✗ API injoignable sur {BASE_URL} ({exc}).")
            print("    Vérifiez qu'elle tourne : docker compose up")
        except ApiError as exc:
            print(f"  ✗ Erreur de l'API (HTTP {exc.status}) : {exc.detail}")
        except (EOFError, KeyboardInterrupt):
            print()
            break
    print("Au revoir !")


if __name__ == "__main__":
    main()
