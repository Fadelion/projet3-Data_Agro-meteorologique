import hashlib
import json
import os
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from random import randint

import pandas as pd
import requests

COORDINATES_PATH = "./data/admin2_coordinates.csv"
OUTPUT_PATH = "./data/meteo_admin2_2010_2022.csv"
CACHE_DIR = "./data/open_meteo_cache_admin2"
API_URL = "https://archive-api.open-meteo.com/v1/archive"
START_DATE = "2010-01-01"
END_DATE = "2022-12-31"
BATCH_SIZE = 20
MAX_RETRIES = 8
DAILY_VARIABLES = [
    "precipitation_sum",
    "temperature_2m_max",
    "temperature_2m_min",
    "relative_humidity_2m_max",
    "relative_humidity_2m_min",
    "wind_speed_10m_max",
]
OUTPUT_COLUMNS = {
    "time": "date",
    "precipitation_sum": "precipitation_mm",
    "temperature_2m_max": "temp_max_c",
    "temperature_2m_min": "temp_min_c",
    "relative_humidity_2m_max": "humidite_max_pct",
    "relative_humidity_2m_min": "humidite_min_pct",
    "wind_speed_10m_max": "vent_max_kmh",
}
FINAL_COLUMNS = [
    "country",
    "admin_2",
    "latitude",
    "longitude",
    "date",
    "precipitation_mm",
    "temp_max_c",
    "temp_min_c",
    "humidite_max_pct",
    "humidite_min_pct",
    "vent_max_kmh",
]


def retry_delay(response, attempt):
    retry_after = response.headers.get("Retry-After")
    if retry_after:
        try:
            return max(1, int(float(retry_after)))
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                return max(1, int((retry_at - datetime.now(timezone.utc)).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                pass
    return min(60 * (2**attempt), 900) + randint(0, 10)


def request_with_retry(params):
    for attempt in range(MAX_RETRIES + 1):
        response = requests.get(API_URL, params=params, timeout=180)
        if response.status_code == 429:
            if attempt == MAX_RETRIES:
                response.raise_for_status()
            delay = retry_delay(response, attempt)
            print(f"  Limite API (429), nouvel essai dans {delay} s...")
            time.sleep(delay)
            continue
        response.raise_for_status()
        return response.json()

    raise RuntimeError("Nombre maximal de tentatives Open-Meteo dépassé")


def cache_path_for(batch, params):
    cache_key_data = {
        "params": params,
        "locations": batch[["country", "admin_2"]].astype(str).values.tolist(),
    }
    cache_key = hashlib.sha256(
        json.dumps(cache_key_data, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return os.path.join(CACHE_DIR, f"{cache_key}.json")


def save_cache(cache_path, data):
    temporary_path = f"{cache_path}.tmp"
    with open(temporary_path, "w", encoding="utf-8") as cache_file:
        json.dump(data, cache_file)
    os.replace(temporary_path, cache_path)

admin2_df = pd.read_csv(COORDINATES_PATH)
admin2_df["latitude"] = pd.to_numeric(admin2_df["latitude"], errors="coerce")
admin2_df["longitude"] = pd.to_numeric(admin2_df["longitude"], errors="coerce")
admin2_df = (
    admin2_df.dropna(subset=["country", "admin_2", "latitude", "longitude"])
    .drop_duplicates(subset=["country", "admin_2"])
    .loc[lambda df: df["admin_2"].str.casefold() != "none"]
    .reset_index(drop=True)
)

os.makedirs(CACHE_DIR, exist_ok=True)
tous_les_df = []
completed_keys = set()

if os.path.exists(OUTPUT_PATH):
    existing_df = pd.read_csv(OUTPUT_PATH)
    if set(FINAL_COLUMNS).issubset(existing_df.columns):
        existing_df = existing_df[FINAL_COLUMNS].copy()
        existing_df["date"] = pd.to_datetime(existing_df["date"], errors="coerce")
        existing_df["latitude"] = pd.to_numeric(existing_df["latitude"], errors="coerce")
        existing_df["longitude"] = pd.to_numeric(existing_df["longitude"], errors="coerce")
        valid_keys = set(zip(admin2_df["country"], admin2_df["admin_2"]))
        existing_df = existing_df.dropna(subset=["date", "latitude", "longitude"])
        existing_df = existing_df[
            existing_df.apply(
                lambda row: (row["country"], row["admin_2"]) in valid_keys,
                axis=1,
            )
        ]

        expected_days = len(pd.date_range(START_DATE, END_DATE, freq="D"))
        summaries = existing_df.groupby(["country", "admin_2"])["date"].agg(
            rows="size",
            days="nunique",
            first="min",
            last="max",
        )
        complete_groups = summaries[
            (summaries["rows"] == expected_days)
            & (summaries["days"] == expected_days)
            & (summaries["first"] == pd.Timestamp(START_DATE))
            & (summaries["last"] == pd.Timestamp(END_DATE))
        ]
        completed_keys = set(complete_groups.index.tolist())
        if completed_keys:
            existing_df = existing_df[
                existing_df.apply(
                    lambda row: (row["country"], row["admin_2"]) in completed_keys,
                    axis=1,
                )
            ]
            tous_les_df.append(existing_df)
            print(f"Reprise depuis le CSV : {len(completed_keys)} admin_2 déjà complets")
    else:
        print("Le CSV existant n'a pas le schéma attendu; il ne sera pas repris.")

pending_mask = [
    (country, admin_2) not in completed_keys
    for country, admin_2 in zip(admin2_df["country"], admin2_df["admin_2"])
]
pending_admin2_df = admin2_df.loc[pending_mask].reset_index(drop=True)
total_batches = (len(pending_admin2_df) + BATCH_SIZE - 1) // BATCH_SIZE

if not total_batches:
    print("Toutes les unités admin_2 sont déjà présentes dans le CSV.")

for batch_number, start in enumerate(range(0, len(pending_admin2_df), BATCH_SIZE), start=1):
    batch = pending_admin2_df.iloc[start : start + BATCH_SIZE]
    params = {
        "latitude": ",".join(batch["latitude"].astype(str)),
        "longitude": ",".join(batch["longitude"].astype(str)),
        "start_date": START_DATE,
        "end_date": END_DATE,
        "daily": ",".join(DAILY_VARIABLES),
        "timezone": "auto",
    }
    batch_cache_path = cache_path_for(batch, params)
    print(f"Téléchargement du lot {batch_number}/{total_batches} ({len(batch)} admin_2)...")

    used_cache = False
    if os.path.exists(batch_cache_path):
        try:
            with open(batch_cache_path, encoding="utf-8") as cache_file:
                data = json.load(cache_file)
            used_cache = True
            print("  Réponse récupérée depuis le cache")
        except (OSError, json.JSONDecodeError):
            print("  Cache illisible; nouvelle requête à Open-Meteo")
            data = request_with_retry(params)
    else:
        data = request_with_retry(params)

    locations_data = data if isinstance(data, list) else [data]
    if len(locations_data) != len(batch):
        raise ValueError(
            f"Open-Meteo a retourné {len(locations_data)} résultats pour {len(batch)} lieux"
        )
    if not used_cache:
        save_cache(batch_cache_path, data)

    for location, weather in zip(batch.itertuples(index=False), locations_data):
        daily = pd.DataFrame(weather.get("daily", {}))
        if daily.empty:
            raise ValueError(f"Pas de données pour {location.admin_2} ({location.country})")

        daily.rename(columns=OUTPUT_COLUMNS, inplace=True)
        daily.insert(0, "country", location.country)
        daily.insert(1, "admin_2", location.admin_2)
        daily.insert(2, "latitude", location.latitude)
        daily.insert(3, "longitude", location.longitude)
        tous_les_df.append(daily)

    print(f"  {len(locations_data)} lieux traités et réponse mise en cache")
    if batch_number < total_batches and not used_cache:
        pause = randint(15, 30)
        print(f"Attente de {pause} secondes...")
        time.sleep(pause)

if tous_les_df:
    final_df = pd.concat(tous_les_df, ignore_index=True)
    final_df = final_df[FINAL_COLUMNS]
    os.makedirs("./data", exist_ok=True)
    temporary_output_path = f"{OUTPUT_PATH}.tmp"
    final_df.to_csv(temporary_output_path, index=False, encoding="utf-8")
    os.replace(temporary_output_path, OUTPUT_PATH)
    print(f"\nFichier sauvegardé : {OUTPUT_PATH}")
    print(
        f"{len(final_df)} lignes | {final_df['admin_2'].nunique()} admin_2 | "
        f"{final_df['country'].nunique()} pays"
    )
    print("Aperçu :")
    print(final_df.head(10).to_string())
else:
    print("Aucune donnée récupérée.")
