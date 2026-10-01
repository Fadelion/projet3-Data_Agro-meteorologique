-- ============================================================
-- Schéma : Statistiques agricoles (HarvestStat Africa) + Météo
-- SGBD   : PostgreSQL
-- ============================================================

BEGIN;

-- ------------------------------------------------------------
-- 1. Hiérarchie géographique : Pays -> region -> departement
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS pays (
    id_pays     SERIAL PRIMARY KEY,
    code_pays   CHAR(2)      NOT NULL UNIQUE,  -- ISO 3166-1 alpha-2, ex. 'BF'
    nom_pays    VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS region (
    id_region   SERIAL PRIMARY KEY,
    id_pays       INTEGER      NOT NULL REFERENCES pays(id_pays),
    nom_region  VARCHAR(150) NOT NULL,
    UNIQUE (id_pays, nom_region)  -- une region porte un nom unique dans son pays
);

CREATE TABLE IF NOT EXISTS departement (
    id_departement     SERIAL PRIMARY KEY,
    id_region  INTEGER       NOT NULL REFERENCES region(id_region),
    nom_departement    VARCHAR(150)  NOT NULL,
    latitude     NUMERIC(8,5),   -- NULL pour les admin_2 d'HarvestStat sans coordonnées
    longitude    NUMERIC(8,5),
    UNIQUE (id_region, nom_departement)
);

-- ------------------------------------------------------------
-- 2. Dimensions agricoles
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS produit (
    id_produit   SERIAL PRIMARY KEY,
    nom_produit  VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE IF NOT EXISTS saison (
    id_saison   SERIAL PRIMARY KEY,
    nom_saison  VARCHAR(100) NOT NULL UNIQUE
);

-- ------------------------------------------------------------
-- 3. Table de faits : Récolte (hvstat_africa_data_v1.0.csv)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS recolte (
    id_recolte          SERIAL PRIMARY KEY,
    id_region         INTEGER NOT NULL REFERENCES region(id_region),
    id_departement            INTEGER REFERENCES departement(id_departement),  -- NULL si admin_2 = "none" (donnée manquante)
    id_produit          INTEGER NOT NULL REFERENCES produit(id_produit),
    id_saison           INTEGER NOT NULL REFERENCES saison(id_saison),
    date_plantation      DATE   NOT NULL,   -- jour fixé à '01' par convention (source : année+mois)
    date_recolte         DATE,              -- idem
    systeme_production   VARCHAR(50),       -- crop_production_system, ex. 'All (PS)'
    surface               NUMERIC(14,2) CHECK (surface >= 0 OR surface = -99),        -- hectares ; -99 = manquant
    production            NUMERIC(14,2) CHECK (production >= 0 OR production = -99),  -- tonnes ; -99 = manquant
    rendement              NUMERIC(10,4) CHECK (rendement >= 0 OR rendement = -99),   -- tonnes/ha ; -99 = manquant
    qc_flag                SMALLINT NOT NULL DEFAULT 0 CHECK (qc_flag IN (0, 1, 2))
);

-- id_departement peut être NULL : PostgreSQL ne considère jamais deux NULL comme
-- égaux dans une contrainte UNIQUE classique, donc une seule UNIQUE(...)
-- ne détecterait pas les doublons parmi les lignes "sans departement". Deux index
-- uniques partiels couvrent les deux cas séparément.
-- Plusieurs systèmes de production peuvent exister pour la même récolte et
-- font partie de la clé métier. PostgreSQL 16 traite aussi deux NULL comme
-- identiques afin de préserver l'unicité si le système est absent.
DROP INDEX IF EXISTS idx_recolte_unique_avec_departement;
DROP INDEX IF EXISTS idx_recolte_unique_sans_departement;

CREATE UNIQUE INDEX IF NOT EXISTS idx_recolte_unique_avec_departement_systeme
    ON recolte (id_departement, id_produit, id_saison, date_plantation, systeme_production)
    NULLS NOT DISTINCT
    WHERE id_departement IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS idx_recolte_unique_sans_departement_systeme
    ON recolte (id_region, id_produit, id_saison, date_plantation, systeme_production)
    NULLS NOT DISTINCT
    WHERE id_departement IS NULL;

-- ------------------------------------------------------------
-- 4. Table de faits : Météo (meteo_afrique_ouest_2010_2022.csv)
-- ------------------------------------------------------------

CREATE TABLE IF NOT EXISTS meteo (
    id_meteo           SERIAL PRIMARY KEY,
    id_departement           INTEGER NOT NULL REFERENCES departement(id_departement),
    date_meteo               DATE    NOT NULL,
    precipitation_mm   NUMERIC(6,2)  NOT NULL CHECK (precipitation_mm >= 0),
    temperature_min    NUMERIC(4,1)  NOT NULL,
    temperature_max    NUMERIC(4,1)  NOT NULL CHECK (temperature_max >= temperature_min),
    humidite_min       SMALLINT      NOT NULL CHECK (humidite_min BETWEEN 0 AND 100),
    humidite_max       SMALLINT      NOT NULL CHECK (humidite_max BETWEEN 0 AND 100
                                                       AND humidite_max >= humidite_min),
    vent               NUMERIC(5,1)  NOT NULL CHECK (vent >= 0),
    UNIQUE (id_departement, date_meteo)
);

-- ------------------------------------------------------------
-- 5. Index utiles pour les requêtes analytiques fréquentes
-- ------------------------------------------------------------

CREATE INDEX IF NOT EXISTS idx_recolte_produit_saison ON recolte (id_produit, id_saison);
CREATE INDEX IF NOT EXISTS idx_recolte_date_plantation ON recolte (date_plantation);
CREATE INDEX IF NOT EXISTS idx_meteo_date ON meteo (date_meteo);

COMMIT;
