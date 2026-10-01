# dbt Harvest

Ce dossier contient le projet dbt du pipeline Agro-Météorologique.

## État actuel

Le projet a été nettoyé du squelette par défaut de dbt et aligné sur les modèles métier du projet.

Les deux tests métier restants sont encore en échec sur les données de la table `recolte`, ce qui correspond à des anomalies réelles de qualité de données dans l’ETL, pas à une erreur de configuration dbt.

## Rapport détaillé

Voir [rapport_dbt.md](rapport_dbt.md).

## Commandes utiles

### Linux / macOS

```bash
source ../.venv/bin/activate
dbt debug
dbt build
```

### Windows (PowerShell)

Depuis la racine du dépôt, créez l'environnement virtuel et installez les dépendances :

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

Puis, toujours depuis la racine du dépôt, lancez dbt avec son exécutable Windows :

```powershell
.\.venv\Scripts\dbt.exe debug
.\.venv\Scripts\dbt.exe build
```
