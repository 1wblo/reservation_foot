-- =============================================================
-- Schema : reservation de terrains de foot interieur
-- =============================================================

-- Extension necessaire pour la contrainte d'exclusion sur les plages horaires.
-- Un index GiST sait comparer des plages (operateur &&) mais pas, de base,
-- un simple entier avec "=". btree_gist ajoute cette capacite, ce qui permet
-- de combiner terrain_id et plage dans une meme contrainte.
CREATE EXTENSION IF NOT EXISTS btree_gist;

CREATE TABLE IF NOT EXISTS client (
    id                SERIAL PRIMARY KEY,
    nom               VARCHAR(50)  NOT NULL,
    prenom            VARCHAR(50)  NOT NULL,
    telephone         VARCHAR(20),
    courriel          VARCHAR(100) UNIQUE,
    date_inscription  DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS type_terrain (
    code        CHAR(1)      PRIMARY KEY,
    nom         VARCHAR(20)  NOT NULL,
    prix_heure  NUMERIC(6,2) NOT NULL CHECK (prix_heure > 0)
);

CREATE TABLE IF NOT EXISTS service (
    code   CHAR(1)      PRIMARY KEY,
    nom    VARCHAR(30)  NOT NULL,
    prix   NUMERIC(6,2) NOT NULL CHECK (prix >= 0)
);

CREATE TABLE IF NOT EXISTS terrain (
    id            SERIAL PRIMARY KEY,
    nom           VARCHAR(30)  NOT NULL,
    surface_m2    NUMERIC(6,2) NOT NULL CHECK (surface_m2 > 0),
    type_code     CHAR(1)      NOT NULL REFERENCES type_terrain(code),
    capacite_max  SMALLINT     NOT NULL CHECK (capacite_max > 0)
);

CREATE TABLE IF NOT EXISTS terrain_service (
    terrain_id    INT     NOT NULL REFERENCES terrain(id) ON DELETE CASCADE,
    service_code  CHAR(1) NOT NULL REFERENCES service(code),
    PRIMARY KEY (terrain_id, service_code)
);

CREATE TABLE IF NOT EXISTS equipement (
    id             SERIAL PRIMARY KEY,
    nom            VARCHAR(30)  NOT NULL,
    prix_unitaire  NUMERIC(6,2) NOT NULL CHECK (prix_unitaire >= 0),
    stock          INT NOT NULL CHECK (stock >= 0)
);

-- Une reservation couvre une plage horaire (timestamptz range).
-- La contrainte EXCLUDE empeche deux reservations CONFIRMEES de se
-- chevaucher sur le meme terrain : c'est Postgres qui garantit
-- l'absence de double-reservation, pas juste le code applicatif.
--
-- Pourquoi dans la base plutot que dans le code ? Verifier avec un SELECT
-- puis inserer laisse une fenetre entre les deux : deux requetes simultanees
-- peuvent chacune ne voir aucun conflit, puis inserer toutes les deux. La
-- contrainte, elle, est verifiee par Postgres au moment de l'insertion,
-- quel que soit le nombre de requetes concurrentes.
--
-- Pourquoi une plage (tstzrange) plutot que deux colonnes debut/fin ? Parce
-- que "ces deux creneaux se chevauchent" s'ecrit alors avec un seul
-- operateur (&&), qu'un index GiST sait verifier efficacement. Une
-- contrainte UNIQUE ne suffirait pas : elle ne detecte que des valeurs
-- identiques, pas 18h-19h contre 18h30-19h30.
CREATE TABLE IF NOT EXISTS reservation (
    id          SERIAL PRIMARY KEY,
    terrain_id  INT NOT NULL REFERENCES terrain(id),
    client_id   INT NOT NULL REFERENCES client(id),
    plage       TSTZRANGE NOT NULL,
    nb_joueurs  SMALLINT NOT NULL CHECK (nb_joueurs > 0),
    statut      VARCHAR(12) NOT NULL DEFAULT 'confirmee'
                CHECK (statut IN ('confirmee', 'annulee')),
    cree_le     TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Une plage vide ne chevauche rien : elle passerait la contrainte
    -- d'exclusion sans jamais occuper le terrain.
    CONSTRAINT chk_plage_non_vide CHECK (NOT isempty(plage)),
    -- Se lit : "il ne peut pas exister deux lignes ayant le meme terrain_id
    -- (=) ET des plages qui se chevauchent (&&)".
    -- Les plages sont creees en '[)' (debut inclus, fin exclue), donc deux
    -- creneaux qui se suivent (18h-19h puis 19h-20h) ne sont pas en conflit.
    -- Le WHERE limite la regle aux reservations confirmees : annuler une
    -- reservation libere son creneau sans avoir a supprimer la ligne, ce
    -- qui conserve l'historique.
    EXCLUDE USING gist (terrain_id WITH =, plage WITH &&)
        WHERE (statut = 'confirmee')
);

CREATE TABLE IF NOT EXISTS reservation_equipement (
    reservation_id  INT NOT NULL REFERENCES reservation(id) ON DELETE CASCADE,
    equipement_id   INT NOT NULL REFERENCES equipement(id),
    quantite        INT NOT NULL CHECK (quantite > 0),
    PRIMARY KEY (reservation_id, equipement_id)
);

-- =============================================================
-- Vue : taux d'occupation par terrain (en heures reservees)
-- =============================================================
-- LEFT JOIN + COALESCE : un terrain sans aucune reservation doit quand meme
-- apparaitre, avec 0 heure. Le filtre sur le statut est dans la condition du
-- JOIN (et non dans un WHERE) pour la meme raison : dans un WHERE, il
-- ferait disparaitre les terrains qui n'ont que des reservations annulees.
CREATE OR REPLACE VIEW occupation_terrain AS
SELECT t.id,
       t.nom,
       COALESCE(SUM(EXTRACT(EPOCH FROM (upper(r.plage) - lower(r.plage))) / 3600), 0) AS heures_reservees
FROM terrain t
LEFT JOIN reservation r ON r.terrain_id = t.id AND r.statut = 'confirmee'
GROUP BY t.id, t.nom;

-- =============================================================
-- Fonction : calcule le prix total d'une reservation
-- (prix du terrain au prorata de la duree + equipements loues)
-- =============================================================
-- Le total n'est pas stocke dans la table reservation : il est recalcule a
-- la demande a partir des prix courants. Une seule source de verite, donc
-- aucun risque qu'un total enregistre ne corresponde plus a ses lignes.
-- (Contrepartie : modifier un prix change aussi le total des reservations
-- passees.)
-- La regle de calcul vit dans la base pour que tout ce qui s'y connecte
-- (API, rapports, psql) obtienne exactement le meme montant.
CREATE OR REPLACE FUNCTION calculer_total_reservation(p_reservation_id INT)
RETURNS NUMERIC AS $$
DECLARE
    v_total         NUMERIC := 0;
    v_prix_terrain  NUMERIC;
    v_duree_heures  NUMERIC;
BEGIN
    -- Duree en heures decimales : la difference des bornes est convertie en
    -- secondes (EPOCH) puis divisee par 3600. Un creneau de 1h30 vaut donc
    -- 1.5, et le terrain est facture au prorata.
    SELECT tt.prix_heure,
           EXTRACT(EPOCH FROM (upper(r.plage) - lower(r.plage))) / 3600
    INTO v_prix_terrain, v_duree_heures
    FROM reservation r
    JOIN terrain t       ON t.id = r.terrain_id
    JOIN type_terrain tt ON tt.code = t.type_code
    WHERE r.id = p_reservation_id;

    -- prix_heure est NOT NULL : s'il est NULL ici, c'est que le SELECT n'a
    -- trouve aucune ligne. On echoue clairement plutot que de retourner un
    -- total a 0 ou NULL qui passerait pour un vrai prix.
    IF v_prix_terrain IS NULL THEN
        RAISE EXCEPTION 'Reservation % introuvable', p_reservation_id;
    END IF;

    v_total := v_prix_terrain * v_duree_heures;

    -- COALESCE : sans equipement loue, SUM retourne NULL, et NULL ajoute
    -- au prix du terrain donnerait un total NULL.
    SELECT v_total + COALESCE(SUM(e.prix_unitaire * re.quantite), 0)
    INTO v_total
    FROM reservation_equipement re
    JOIN equipement e ON e.id = re.equipement_id
    WHERE re.reservation_id = p_reservation_id;

    RETURN ROUND(v_total, 2);
END;
$$ LANGUAGE plpgsql;
