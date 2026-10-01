-- Échoue si une température (min ou max) est absurde (< -50) et n'est pas le code -99
SELECT *
FROM {{ ref('meteo') }}
WHERE (temperature_min < -50 AND temperature_min != -99) 
   OR (temperature_max < -50 AND temperature_max != -99)