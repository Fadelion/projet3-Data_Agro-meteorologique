{{ config(materialized='table') }}

SELECT
    r.id_recolte,
    r.id_departement,
    r.id_produit,
    r.id_saison,
    EXTRACT(YEAR FROM r.date_plantation) AS annee_plantation,
    r.surface,
    r.production,
    r.rendement,
    c.precipitation_totale,
    c.temp_max_moyenne,
    c.temp_min_moyenne
FROM {{ ref('recolte') }} r
LEFT JOIN {{ ref('marts_climat_annuel') }} c
    ON r.id_departement = c.id_departement
    AND EXTRACT(YEAR FROM r.date_plantation) = c.annee
WHERE r.id_departement IS NOT NULL
