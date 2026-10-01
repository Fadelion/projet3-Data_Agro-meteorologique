# Projet Agro-Météorologique - Data Engineering Pipeline

Ce projet met en place un pipeline de données complet (ETL) combinant des données de récolte agricole (HarvestStat) et des données météorologiques historiques pour l'Afrique.

## Architecture du Projet

1. **Extraction et Transformation (ETL)**: Un script Python orchestré par Airflow se charge d'extraire les données depuis des fichiers CSV bruts, de les nettoyer et de les transformer pour respecter le format de la base de données de destination.
2. **Data Warehouse (PostgreSQL)**: Un modèle dimensionnel en flocon ou étoile avec des dimensions (`pays`, `region`, `departement`, `produit`, `saison`) et deux tables de faits (`recolte`, `meteo`).
3. **Orchestration (Apache Airflow)**: Planifie et exécute les tâches d'extraction, de transformation et de chargement (ETL) des données depuis les CSV vers PostgreSQL via un DAG (`harveststat_meteo_pipeline`).
4. **Validation et Modélisation (dbt)**: Applique des tests de qualité de données (tests métiers) et crée des Data Marts analytiques (moyennes annuelles de climat et jointures agro-météo).

## Guide de Déploiement

Le projet s'appuie sur la configuration officielle de déploiement d'Apache Airflow via Docker Compose. Pour plus de détails, consultez la [documentation officielle d'Airflow (Docker Compose)](https://airflow.apache.org/docs/apache-airflow/2.5.0/howto/docker-compose/index.html).

### 1. Prérequis

Assurez-vous que Docker et Docker Compose sont installés sur votre machine, et que les fichiers de données volumineux se trouvent dans `dags/data/` :

- `dags/data/hvstat_africa_data_v1.0.csv`
- `dags/data/meteo_admin2_2010_2022.csv`

#### Sous Windows

Installez Docker Desktop for Windows, activez le moteur WSL 2 et démarrez Docker Desktop avant de lancer le projet. Ouvrez PowerShell à la racine du dépôt et vérifiez que les deux fichiers CSV requis sont présents dans `dags/data/`.

Les commandes Docker Compose v2 utilisées ci-dessous sont identiques dans PowerShell :

```powershell
docker compose up -d --build
docker compose logs warehouse-init
```

Le script `airflow.sh` étant un script Bash, ne l'exécutez pas directement dans PowerShell. Utilisez les commandes `docker compose` depuis la racine du projet.

### 2. Lancer l'infrastructure (Airflow + PostgreSQL)

À la racine du projet, lancez Docker Compose :

```bash
docker compose up -d --build
```

*Note : Le fichier `docker-compose.override.yml` est automatiquement détecté et ajoute une base de données PostgreSQL distincte (`postgres_harveststat` exposée sur le port `5433`) qui servira de Data Warehouse.*

### 3. Initialisation automatique

Au démarrage, Docker Compose attend que PostgreSQL soit prêt, applique `init_schema.sql` au Data Warehouse, puis initialise Airflow. Les chemins des deux CSV sont fournis automatiquement à tous les services Airflow via leur environnement; aucune commande `airflow variables set` n'est nécessaire.

Le schéma peut être appliqué à chaque démarrage, y compris avec un volume PostgreSQL déjà créé. Les tables et index existants sont conservés; ce mécanisme ne remplace pas une migration lorsqu'une définition de table évolue.

```bash
docker compose logs warehouse-init
```

### 4. Lancer le DAG (Pipeline ETL)

1. Rendez-vous sur l'interface graphique Airflow à l'adresse [http://localhost:8080](http://localhost:8080) (Identifiants par défaut : `airflow` / `airflow`).
2. Cherchez le DAG `harveststat_meteo_pipeline`.
3. Cliquez sur le bouton "Trigger DAG" (play) pour exécuter manuellement l'intégration des données.

### 5. Validation et Transformation avec dbt

Une fois les données chargées en base, activez votre environnement Python (contenant dbt) et placez-vous dans le répertoire `dbt_harvest`.

**Pour exécuter les tests métiers (qualité des données) :**

```bash
cd dbt_harvest
dbt test
```

*Tests inclus : Cohérence des températures, intégrité des rendements, validations des dates de récolte, vérification des champs null, etc.*

**Pour générer les Data Marts analytiques (Tables consolidées) :**

```bash
dbt run
```

*Génère entre autres la table `marts_agro_meteo` liant l'agriculture et le climat par année et par département.*
