#!/usr/bin/env bash
set -euo pipefail

# Resolve paths relative to this script so it can be launched from any directory.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_DIR"

# Public Google Drive file IDs used only when the corresponding CSV is missing.
HVSTAT_DRIVE_ID="100DQ_Pkb8uZMASgd5KQ63Rrxs02-sO42"
METEO_DRIVE_ID="1xvDXCJDmDUogX5ZxwPLQ8_d09FeIeIcy"

fail() {
    printf 'Erreur : %s\n' "$1" >&2
    exit 1
}

# Require Docker Compose v2 and an already-running Docker engine.
command -v python3 >/dev/null 2>&1 || fail "Python 3 est requis. Installez-le puis relancez setup.sh."
command -v docker >/dev/null 2>&1 || fail "Docker CLI est introuvable. Installez Docker puis relancez setup.sh."
docker compose version >/dev/null 2>&1 || fail "Docker Compose v2 est requis (commande 'docker compose')."
docker info >/dev/null 2>&1 || fail "Le moteur Docker ne semble pas demarre. Demarrez Docker Desktop ou le service Docker, puis relancez setup.sh."

# Create the isolated Python environment once, then install project dependencies.
mkdir -p dags/data

if [[ ! -d .venv ]]; then
    printf 'Creation de l environnement Python...\n'
    python3 -m venv .venv || fail "Impossible de creer .venv. Verifiez que le module venv est installe."
fi

VENV_PYTHON="$PROJECT_DIR/.venv/bin/python"
[[ -x "$VENV_PYTHON" ]] || fail "L'interpreteur .venv est introuvable : $VENV_PYTHON"
printf 'Installation des dependances Python...\n'
"$VENV_PYTHON" -m pip install --upgrade pip
"$VENV_PYTHON" -m pip install -r requirements.txt

# Keep existing data untouched; download a missing CSV to the Airflow-mounted folder.
fetch_csv_if_missing() {
    local filename="$1"
    local drive_id="$2"
    local destination="$PROJECT_DIR/dags/data/$filename"

    if [[ -s "$destination" ]]; then
        printf 'CSV deja present : dags/data/%s\n' "$filename"
        return
    fi

    printf 'Telechargement depuis Google Drive : %s\n' "$filename"
    "$VENV_PYTHON" -c 'import gdown, sys; result = gdown.download(id=sys.argv[1], output=sys.argv[2]); sys.exit(0 if result else 1)' "$drive_id" "$destination" || {
        rm -f "$destination"
        fail "Echec du telechargement de $filename. Verifiez que le fichier Drive est accessible a toute personne disposant du lien."
    }

    [[ -s "$destination" ]] || fail "Le telechargement de $filename n'a produit aucun fichier."
}

fetch_csv_if_missing "hvstat_africa_data_v1.0.csv" "$HVSTAT_DRIVE_ID"
fetch_csv_if_missing "meteo_admin2_2010_2022.csv" "$METEO_DRIVE_ID"

# Preserve local settings and initialize the template only for a new checkout.
if [[ ! -f .env ]]; then
    cp .env.example .env || fail "Impossible de creer .env a partir de .env.example."
    printf 'Fichier .env cree depuis .env.example.\n'
fi

# Generate Fernet material only when .env has no non-empty key.
if ! grep -Eq '^[[:space:]]*FERNET_KEY[[:space:]]*=[[:space:]]*[^[:space:]#]+' .env; then
    FERNET_KEY="$("$VENV_PYTHON" -c 'import base64, secrets; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())')"
    printf '\nFERNET_KEY=%s\n' "$FERNET_KEY" >> .env
    printf 'Cle Fernet generee et ajoutee a .env.\n'
fi

# Start Airflow and PostgreSQL after local prerequisites are ready.
printf 'Demarrage des services Docker Compose...\n'
docker compose up -d --build
printf 'Setup termine. Airflow est disponible sur http://localhost:8080.\n'
