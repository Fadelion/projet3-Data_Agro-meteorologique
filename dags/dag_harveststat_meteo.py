"""
DAG Airflow : pipeline HarvestStat Africa + météo Afrique de l'Ouest.

Orchestration extract -> transform -> load. La logique métier vit dans
etl_lib.py (module réutilisé par etl_harveststat_meteo.py pour une
exécution manuelle) ; ce fichier reste un mince fichier d'orchestration,
comme recommandé pour les DAG Airflow.

Les DataFrames ne transitent JAMAIS par XCom (trop volumineux : 203 125
lignes HarvestStat, 28 488 lignes météo -- XCom est prévu pour de
petites valeurs, pas des DataFrames). Chaque étape écrit un fichier
parquet dans STAGING_DIR et ne passe que le CHEMIN via XCom.

Prérequis Airflow (à faire une fois, dans l'UI ou via .env -- voir
la configuration Docker Compose) :
    - Connexion Postgres nommée `postgres_harveststat`
        - chemins des CSV fournis automatiquement par Docker Compose via
            AIRFLOW_VAR_HVSTAT_CSV_PATH et AIRFLOW_VAR_METEO_CSV_PATH
        - fichiers sources sous /opt/airflow/dags/data/ (volume partagé
            par tous les services Airflow, y compris les workers Celery)
    - pip install apache-airflow-providers-postgres pandas sqlalchemy
      psycopg2-binary pyarrow (via _PIP_ADDITIONAL_REQUIREMENTS)
    - etl_lib.py doit être déposé dans le même dossier que ce DAG

Ce DAG ne fait PAS de validation de qualité des données (unicité,
non-nullité, plages de valeurs) : c'est le rôle de dbt (étape suivante
de la feuille de route), pas d'Airflow ici.
"""

import sys
from pathlib import Path

import pandas as pd
from airflow.sdk import Variable, dag, task
from airflow.providers.postgres.hooks.postgres import PostgresHook
from pendulum import datetime

# Garantit que etl_lib.py (déposé dans le même dossier que ce DAG) est
# importable, même si le dossier du DAG n'est pas déjà sur sys.path
# selon la configuration Airflow.
sys.path.append(str(Path(__file__).parent))
import etl_lib

DEFAULT_STAGING_DIR = "/opt/airflow/dags/data/staging"
POSTGRES_CONN_ID = "postgres_harveststat"


def get_staging_dir() -> Path:
    return Path(Variable.get("harveststat_staging_dir", default=DEFAULT_STAGING_DIR))

default_args = {
    "owner": "fay",
    "retries": 1,
}


@dag(
    dag_id="harveststat_meteo_pipeline",
    description="HarvestStat Africa + météo Afrique de l'Ouest -> PostgreSQL",
    schedule=None,  # déclenchement manuel par défaut ; à remplacer par un cron si besoin
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args=default_args,
    tags=["harveststat", "meteo", "etl"],
)
def harveststat_meteo_pipeline():
    @task()
    def extract_hvstat(ds=None) -> str:
        path = Variable.get("hvstat_csv_path")
        df = etl_lib.extract_hvstat(path)
        staging_dir = get_staging_dir()
        staging_dir.mkdir(parents=True, exist_ok=True)
        out_path = staging_dir / f"hvstat_raw_{ds}.parquet"
        df.to_parquet(out_path, index=False)
        return str(out_path)

    @task()
    def extract_meteo(ds=None) -> str:
        path = Variable.get("meteo_csv_path")
        df = etl_lib.extract_meteo(path)
        staging_dir = get_staging_dir()
        staging_dir.mkdir(parents=True, exist_ok=True)
        out_path = staging_dir / f"meteo_raw_{ds}.parquet"
        df.to_parquet(out_path, index=False)
        return str(out_path)

    @task()
    def transform_hvstat(raw_path: str, ds=None) -> str:
        df = pd.read_parquet(raw_path)
        df = etl_lib.transform_hvstat(df)
        out_path = get_staging_dir() / f"hvstat_clean_{ds}.parquet"
        df.to_parquet(out_path, index=False)
        return str(out_path)

    @task()
    def transform_meteo(raw_path: str, ds=None) -> str:
        df = pd.read_parquet(raw_path)
        df = etl_lib.transform_meteo(df)
        out_path = get_staging_dir() / f"meteo_clean_{ds}.parquet"
        df.to_parquet(out_path, index=False)
        return str(out_path)

    @task()
    def load(hvstat_clean_path: str, meteo_clean_path: str) -> dict:
        engine = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID).get_sqlalchemy_engine()
        df_hvstat = pd.read_parquet(hvstat_clean_path)
        df_meteo = pd.read_parquet(meteo_clean_path)

        etl_lib.load_dimensions(engine, df_hvstat, df_meteo)
        compteurs = etl_lib.load_facts(engine, df_hvstat, df_meteo)
        return compteurs

    hvstat_raw = extract_hvstat()
    meteo_raw = extract_meteo()
    hvstat_clean = transform_hvstat(hvstat_raw)
    meteo_clean = transform_meteo(meteo_raw)
    load(hvstat_clean, meteo_clean)


harveststat_meteo_pipeline()
