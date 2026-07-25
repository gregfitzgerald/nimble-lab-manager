-- Monthly reagent spend, with a running cumulative total.
-- Uses a window function (SUM OVER) -- demonstrates analytics beyond basic aggregation.

WITH monthly AS (
    SELECT
        strftime('%Y-%m', order_date) AS month,
        SUM(quantity * unit_cost)      AS spend
    FROM orders
    GROUP BY strftime('%Y-%m', order_date)
)
SELECT
    month,
    ROUND(spend, 2) AS monthly_spend,
    ROUND(SUM(spend) OVER (ORDER BY month), 2) AS cumulative_spend
FROM monthly
ORDER BY month;
