-- La règle métier valide le cycle agricole saisonnier courant : une récolte en
-- décembre et une plantation en janvier de l'année suivante appartiennent au même
-- cycle. Les vraies anomalies sont les dates inversées en dehors de ce motif.
SELECT *
FROM {{ ref('recolte') }}
WHERE date_plantation IS NOT NULL
  AND date_recolte IS NOT NULL
  AND date_recolte < date_plantation
  AND NOT (
      EXTRACT(MONTH FROM date_plantation) = 1
      AND EXTRACT(MONTH FROM date_recolte) = 12
      AND EXTRACT(YEAR FROM date_recolte) = EXTRACT(YEAR FROM date_plantation) - 1
  )
