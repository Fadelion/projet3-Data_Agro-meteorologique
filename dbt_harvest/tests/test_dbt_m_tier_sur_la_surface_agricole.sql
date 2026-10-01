-- Échoue si une surface est négative et n'est pas le code -99
SELECT *
FROM {{ ref('recolte') }}
WHERE surface < 0 AND surface != -99