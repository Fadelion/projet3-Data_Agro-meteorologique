"""
Bibliothèque extract/transform/load pour le pipeline HarvestStat Africa
+ météo Afrique de l'Ouest -> PostgreSQL (schema_harveststat_meteo.sql).

Aucune dépendance à Airflow ici : ce module est testable seul, et est
utilisé à la fois par etl_harveststat_meteo.py (exécution manuelle en
une passe) et par dag_harveststat_meteo.py (orchestration Airflow).

Découpage délibéré :
    - EXTRACT  : lecture brute, aucune logique métier.
    - TRANSFORM: opérations indépendantes de la base cible (dates,
      -99, mapping pays FR->EN). Ne résout PAS les clés étrangères.
    - LOAD     : résout les clés étrangères (pays/region/departement/
      produit/saison) et écrit en base. Ça dépend de ce qui existe
      déjà en base (ON CONFLICT DO NOTHING sur les dimensions), donc
      ça ne peut pas être fait dans TRANSFORM sans toucher la cible.
"""

import sys

import pandas as pd
from sqlalchemy import MetaData, Table
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import text

# À compléter avec les pays réellement présents dans ton CSV météo.
COUNTRY_FR_TO_EN = {
    "Sénégal": "Senegal",
    # "...": "...",
}


# ------------------------------------------------------------------
# EXTRACT
# ------------------------------------------------------------------
def extract_hvstat(path):
    df = pd.read_csv(path)
    if "fnid" not in df.columns:
        df = df.reset_index().rename(columns={"index": "fnid"})
    return df


def extract_meteo(path):
    df = pd.read_csv(path)
    dates = pd.to_datetime(df["date"], format="mixed", errors="raise")
    if dates.isna().any():
        invalid_rows = dates[dates.isna()].index[:5].tolist()
        raise ValueError(f"Dates météo manquantes aux lignes CSV (index pandas) : {invalid_rows}")
    df["date"] = dates
    return df


# ------------------------------------------------------------------
# TRANSFORM
# ------------------------------------------------------------------
def transform_hvstat(df):
    df = df.copy()
    df["date_plantation"] = pd.to_datetime(
        pd.DataFrame({"year": df["planting_year"], "month": df["planting_month"], "day": 1})
    )
    df["date_recolte"] = pd.to_datetime(
        pd.DataFrame({"year": df["harvest_year"], "month": df["harvest_month"], "day": 1})
    )
    # Convention du projet : valeurs manquantes -> -99 (pas NULL)
    df[["area", "production", "yield"]] = df[["area", "production", "yield"]].fillna(-99)
    return df


def transform_meteo(df):
    df = df.copy()
    if "country" in df.columns:
        df["pays_en"] = df["country"]
    else:
        df["pays_en"] = df["pays"].map(COUNTRY_FR_TO_EN)
    
    if "admin_2" in df.columns:
        df["departement"] = df["admin_2"]
    return df


# ------------------------------------------------------------------
# LOAD : dimensions
# ------------------------------------------------------------------
def load_pays(engine, df_hvstat):
    pays = df_hvstat[["country", "country_code"]].drop_duplicates()
    with engine.begin() as conn:
        for _, row in pays.iterrows():
            conn.execute(
                text(
                    "INSERT INTO pays (nom_pays, code_pays) "
                    "VALUES (:nom_pays, :code_pays) "
                    "ON CONFLICT (nom_pays) DO NOTHING"
                ),
                {"nom_pays": row["country"], "code_pays": row["country_code"]},
            )
    return pd.read_sql("SELECT id_pays, nom_pays, code_pays FROM pays", engine)


def load_region(engine, df_hvstat, dim_pays):
    df = df_hvstat[["country", "admin_1"]].drop_duplicates()
    df = df.merge(dim_pays, left_on="country", right_on="nom_pays")
    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text(
                    "INSERT INTO region (id_pays, nom_region) "
                    "VALUES (:id_pays, :nom_region) "
                    "ON CONFLICT (id_pays, nom_region) DO NOTHING"
                ),
                {"id_pays": int(row["id_pays"]), "nom_region": row["admin_1"]},
            )
    return pd.read_sql("SELECT id_region, id_pays, nom_region FROM region", engine)


def load_departement_from_hvstat(engine, df_hvstat, dim_pays, dim_region):
    df = df_hvstat[["country", "admin_1", "admin_2"]].drop_duplicates()
    df = df[df["admin_2"] != "none"]  # "none" = donnée manquante, pas une departement
    df = df.merge(dim_pays, left_on="country", right_on="nom_pays")
    df = df.merge(dim_region, left_on=["id_pays", "admin_1"], right_on=["id_pays", "nom_region"])
    with engine.begin() as conn:
        for _, row in df.iterrows():
            conn.execute(
                text(
                    "INSERT INTO departement (id_region, nom_departement) "
                    "VALUES (:id_region, :nom_departement) "
                    "ON CONFLICT (id_region, nom_departement) DO NOTHING"
                ),
                {"id_region": int(row["id_region"]), "nom_departement": row["admin_2"]},
            )


def attach_meteo_departements(engine, df_meteo):
    """Rattache les departements météo à des departements HarvestStat existantes
    (pays traduit + nom exact) et met à jour latitude/longitude.
    Retourne la liste des departements météo non reconnues."""
    departements = df_meteo[["departement", "pays_en", "latitude", "longitude"]].drop_duplicates()
    non_reconnues = []
    with engine.begin() as conn:
        for _, row in departements.iterrows():
            if pd.isna(row["pays_en"]):
                non_reconnues.append(row["departement"])
                continue
            result = conn.execute(
                text(
                    "SELECT v.id_departement FROM departement v "
                    "JOIN region p ON p.id_region = v.id_region "
                    "JOIN pays pa ON pa.id_pays = p.id_pays "
                    "WHERE pa.nom_pays = :pays AND v.nom_departement = :departement"
                ),
                {"pays": row["pays_en"], "departement": row["departement"]},
            ).fetchone()
            if result is None:
                non_reconnues.append(row["departement"])
                continue
            conn.execute(
                text(
                    "UPDATE departement SET latitude = :lat, longitude = :lon "
                    "WHERE id_departement = :id_departement"
                ),
                {"lat": row["latitude"], "lon": row["longitude"], "id_departement": result[0]},
            )
    if non_reconnues:
        print(
            f"[ATTENTION] {len(non_reconnues)} departement(s) météo sans correspondance "
            f"dans HarvestStat : {sorted(set(non_reconnues))}",
            file=sys.stderr,
        )
    return non_reconnues


def load_produit(engine, df_hvstat):
    with engine.begin() as conn:
        for p in df_hvstat["product"].dropna().unique():
            conn.execute(
                text(
                    "INSERT INTO produit (nom_produit) VALUES (:p) "
                    "ON CONFLICT (nom_produit) DO NOTHING"
                ),
                {"p": p},
            )
    return pd.read_sql("SELECT id_produit, nom_produit FROM produit", engine)


def load_saison(engine, df_hvstat):
    with engine.begin() as conn:
        for s in df_hvstat["season_name"].dropna().unique():
            conn.execute(
                text(
                    "INSERT INTO saison (nom_saison) VALUES (:s) "
                    "ON CONFLICT (nom_saison) DO NOTHING"
                ),
                {"s": s},
            )
    return pd.read_sql("SELECT id_saison, nom_saison FROM saison", engine)


def load_dimensions(engine, df_hvstat, df_meteo):
    dim_pays = load_pays(engine, df_hvstat)
    dim_region = load_region(engine, df_hvstat, dim_pays)
    load_departement_from_hvstat(engine, df_hvstat, dim_pays, dim_region)
    attach_meteo_departements(engine, df_meteo)
    load_produit(engine, df_hvstat)
    load_saison(engine, df_hvstat)


# ------------------------------------------------------------------
# LOAD : faits
# ------------------------------------------------------------------
def _append_ignoring_conflicts(
    df,
    engine,
    table_name,
    index_elements,
    partial_column=None,
    partial_is_null=None,
):
    target_table = None

    def insert_no_conflicts(pd_table, conn, keys, data_iter):
        nonlocal target_table

        rows = [dict(zip(keys, row)) for row in data_iter]
        if not rows:
            return 0

        if target_table is None:
            target_table = Table(table_name, MetaData(), autoload_with=conn)

        index_where = None
        if partial_column is not None:
            column = target_table.c[partial_column]
            index_where = column.is_(None) if partial_is_null else column.is_not(None)

        statement = pg_insert(target_table).values(rows).on_conflict_do_nothing(
            index_elements=[target_table.c[column] for column in index_elements],
            index_where=index_where,
        )
        return conn.execute(statement).rowcount

    df.to_sql(
        table_name,
        engine,
        if_exists="append",
        index=False,
        method=insert_no_conflicts,
        chunksize=1000,
    )


def load_recolte(engine, df_hvstat):
    dim_pays = pd.read_sql("SELECT id_pays, nom_pays FROM pays", engine)
    dim_region = pd.read_sql("SELECT id_region, id_pays, nom_region FROM region", engine)
    dim_departement = pd.read_sql("SELECT id_departement, id_region, nom_departement FROM departement", engine)
    dim_produit = pd.read_sql("SELECT id_produit, nom_produit FROM produit", engine)
    dim_saison = pd.read_sql("SELECT id_saison, nom_saison FROM saison", engine)

    n_avant = len(df_hvstat)
    df = df_hvstat.merge(dim_pays, left_on="country", right_on="nom_pays")
    df = df.merge(dim_region, left_on=["id_pays", "admin_1"], right_on=["id_pays", "nom_region"])
    df = df.merge(dim_produit, left_on="product", right_on="nom_produit")
    df = df.merge(dim_saison, left_on="season_name", right_on="nom_saison")

    avec_departement = df[df["admin_2"] != "none"].merge(
        dim_departement, left_on=["id_region", "admin_2"], right_on=["id_region", "nom_departement"]
    )
    sans_departement = df[df["admin_2"] == "none"].copy()
    sans_departement["id_departement"] = pd.NA
    df = pd.concat([avec_departement, sans_departement], ignore_index=True)

    n_apres = len(df)
    if n_apres < n_avant:
        print(
            f"[ATTENTION] {n_avant - n_apres} ligne(s) HarvestStat non rattachées "
            f"aux dimensions, non chargées dans recolte.",
            file=sys.stderr,
        )

    lignes = df[
        [
            "id_region", "id_departement", "id_produit", "id_saison", "date_plantation", "date_recolte",
            "crop_production_system", "area", "production", "yield", "qc_flag",
        ]
    ].rename(
        columns={
            "crop_production_system": "systeme_production",
            "area": "surface",
            "yield": "rendement",
        }
    )
    avec_departement = lignes[lignes["id_departement"].notna()]
    sans_departement = lignes[lignes["id_departement"].isna()]
    _append_ignoring_conflicts(
        avec_departement,
        engine,
        "recolte",
        ("id_departement", "id_produit", "id_saison", "date_plantation", "systeme_production"),
        partial_column="id_departement",
        partial_is_null=False,
    )
    _append_ignoring_conflicts(
        sans_departement,
        engine,
        "recolte",
        ("id_region", "id_produit", "id_saison", "date_plantation", "systeme_production"),
        partial_column="id_departement",
        partial_is_null=True,
    )
    return len(lignes)


def load_meteo(engine, df_meteo):
    dim_departement = pd.read_sql(
        "SELECT v.id_departement, v.nom_departement, pa.nom_pays "
        "FROM departement v JOIN region p ON p.id_region = v.id_region "
        "JOIN pays pa ON pa.id_pays = p.id_pays",
        engine,
    )
    df = df_meteo.merge(dim_departement, left_on=["departement", "pays_en"], right_on=["nom_departement", "nom_pays"])

    ignorees = df_meteo["departement"].nunique() - df["departement"].nunique()
    if ignorees:
        print(f"[ATTENTION] {ignorees} departement(s) météo ignorée(s) faute de correspondance.", file=sys.stderr)

    lignes = df[
        [
            "id_departement", "date", "precipitation_mm", "temp_max_c", "temp_min_c",
            "humidite_max_pct", "humidite_min_pct", "vent_max_kmh",
        ]
    ].rename(
        columns={
            "temp_max_c": "temperature_max",
            "temp_min_c": "temperature_min",
            "humidite_max_pct": "humidite_max",
            "humidite_min_pct": "humidite_min",
            "vent_max_kmh": "vent",
            "date": "date_meteo",
        }
    )
    _append_ignoring_conflicts(
        lignes,
        engine,
        "meteo",
        ("id_departement", "date_meteo"),
    )
    return len(lignes)


def load_facts(engine, df_hvstat, df_meteo):
    n_recolte = load_recolte(engine, df_hvstat)
    n_meteo = load_meteo(engine, df_meteo)
    return {"recolte": n_recolte, "meteo": n_meteo}
