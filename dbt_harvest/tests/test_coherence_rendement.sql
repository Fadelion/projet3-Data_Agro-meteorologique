-- Les valeurs extrêmes restent anormales ; la tolérance est fixée au-delà des
-- écarts de mesure observés dans les données agricoles du projet.
SELECT *
FROM {{ ref('recolte') }}
WHERE surface > 0
  AND production > 0
  AND rendement != -99
  AND ABS((production / surface) - rendement) > 5.0
