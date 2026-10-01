{{ config(materialized='table') }}

SELECT
    id_departement,
    EXTRACT(YEAR FROM date_meteo) AS annee,
    SUM(precipitation_mm) AS precipitation_totale,
    AVG(temperature_max) AS temp_max_moyenne,
    AVG(temperature_min) AS temp_min_moyenne
FROM {{ ref('meteo') }}
GROUP BY id_departement, EXTRACT(YEAR FROM date_meteo)
