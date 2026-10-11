-- =============================================================
-- Donnees de demonstration
-- =============================================================

INSERT INTO type_terrain (code, nom, prix_heure) VALUES
    ('5', '5 contre 5',  60.00),
    ('7', '7 contre 7',  90.00),
    ('O', '11 contre 11', 150.00)
ON CONFLICT (code) DO NOTHING;

INSERT INTO service (code, nom, prix) VALUES
    ('V', 'Vestiaire prive', 10.00),
    ('E', 'Eclairage LED',    8.00),
    ('A', 'Arbitre',         25.00)
ON CONFLICT (code) DO NOTHING;

INSERT INTO terrain (nom, surface_m2, type_code, capacite_max) VALUES
    ('Terrain A', 400.00, '5', 10),
    ('Terrain B', 650.00, '7', 14),
    ('Terrain C', 1000.00, 'O', 22)
ON CONFLICT DO NOTHING;

INSERT INTO terrain_service (terrain_id, service_code) VALUES
    (1, 'V'), (1, 'E'),
    (2, 'V'), (2, 'E'), (2, 'A'),
    (3, 'V'), (3, 'E'), (3, 'A')
ON CONFLICT DO NOTHING;

INSERT INTO equipement (nom, prix_unitaire, stock) VALUES
    ('Ballon',        5.00, 20),
    ('Dossard (jeu de 10)', 15.00, 8),
    ('Plots (jeu de 20)',   8.00, 10)
ON CONFLICT DO NOTHING;

INSERT INTO client (nom, prenom, telephone, courriel) VALUES
    ('Tremblay', 'Alex',   '514-555-2001', 'alex.tremblay@example.com'),
    ('Nguyen',   'Mai',    '514-555-2002', 'mai.nguyen@example.com'),
    ('Diallo',   'Omar',   '514-555-2003', 'omar.diallo@example.com')
ON CONFLICT DO NOTHING;
