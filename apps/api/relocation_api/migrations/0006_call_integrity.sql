-- One live call per PG per mover, enforced by the database, not just by a check in the code.
--
-- A check followed by an insert can be raced: two requests at the same moment both pass the
-- check and both insert, and an owner is called twice. A unique index cannot be raced.

ALTER TABLE calls ADD COLUMN plan_id uuid REFERENCES move_plans(id);

UPDATE calls c SET plan_id = b.plan_id
FROM call_batches b
WHERE b.id = c.batch_id;

-- If duplicates already exist, keep one live call per plan and PG and retire the rest, so the
-- index below can be created. (A failed or unreachable call does not count as live.)
WITH ranked AS (
    SELECT id,
           row_number() OVER (PARTITION BY plan_id, pg_id ORDER BY started_at NULLS LAST, id) AS rn
    FROM calls
    WHERE plan_id IS NOT NULL AND status NOT IN ('failed', 'unreachable')
)
UPDATE calls
SET status = 'failed', end_reason = 'duplicate_removed', ended_at = COALESCE(ended_at, now())
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

CREATE UNIQUE INDEX calls_one_live_per_pg_and_plan
    ON calls (plan_id, pg_id)
    WHERE plan_id IS NOT NULL AND status NOT IN ('failed', 'unreachable');
