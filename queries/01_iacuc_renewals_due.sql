-- Which IACUC protocols are overdue or due within the next 60 days?
-- Missing a renewal can halt all animal work, so this is the query a lab manager runs weekly.
-- SQLite: date('now') = current date. On Postgres, replace date('now') with CURRENT_DATE.

SELECT
    p.protocol_id,
    p.title,
    s.full_name AS pi,
    p.renewal_due,
    CAST(julianday(p.renewal_due) - julianday(date('now')) AS INTEGER) AS days_until_due,
    CASE
        WHEN p.renewal_due < date('now') THEN 'OVERDUE'
        ELSE 'DUE SOON'
    END AS flag
FROM protocols p
JOIN staff s ON s.staff_id = p.pi_staff_id
WHERE p.status = 'active'
  AND p.renewal_due <= date('now', '+60 day')
ORDER BY p.renewal_due;
