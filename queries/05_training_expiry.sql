-- Staff training that is expired or expires within 90 days.
-- Expired safety/IACUC training can pull a person off approved protocols, so managers track it proactively.

SELECT
    s.full_name,
    s.role,
    t.course,
    t.expires_date,
    CAST(julianday(t.expires_date) - julianday(date('now')) AS INTEGER) AS days_until_expiry,
    CASE
        WHEN t.expires_date < date('now') THEN 'EXPIRED'
        ELSE 'EXPIRING SOON'
    END AS flag
FROM training t
JOIN staff s ON s.staff_id = t.staff_id
WHERE t.expires_date <= date('now', '+90 day')
ORDER BY t.expires_date;
