-- Which reagents are at or below their reorder threshold, and what would restocking cost?
-- Restock target: bring each item up to 2x its threshold.

SELECT
    item_id,
    item_name,
    vendor,
    quantity_on_hand,
    reorder_threshold,
    (2 * reorder_threshold - quantity_on_hand) AS suggested_order_qty,
    ROUND((2 * reorder_threshold - quantity_on_hand) * unit_cost, 2) AS estimated_cost
FROM inventory
WHERE quantity_on_hand <= reorder_threshold
ORDER BY estimated_cost DESC;
