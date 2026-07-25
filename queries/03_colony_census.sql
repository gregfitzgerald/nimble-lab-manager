-- Live colony census by strain and sex, with average age in weeks.
-- Only counts animals currently alive (excludes euthanized / transferred).

SELECT
    strain,
    sex,
    COUNT(*) AS n_alive,
    ROUND(AVG(julianday(date('now')) - julianday(date_of_birth)) / 7.0, 1) AS avg_age_weeks
FROM animals
WHERE status = 'alive'
GROUP BY strain, sex
ORDER BY strain, sex;
