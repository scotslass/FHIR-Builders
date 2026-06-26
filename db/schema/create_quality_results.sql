-- Optional persisted store for quality-check results, for trend analysis.
-- One row per violation per run. Load the report CSVs into this table to track
-- data quality over time.

CREATE TABLE IF NOT EXISTS quality_results (
    run_date       DATE        NOT NULL,
    rule_id        VARCHAR     NOT NULL,
    severity       VARCHAR,                -- error | warning | info (empty for could_not_assess)
    status         VARCHAR     NOT NULL DEFAULT 'fail',  -- fail | could_not_assess
    resource_type  VARCHAR     NOT NULL,
    resource_id    VARCHAR     NOT NULL,
    message        VARCHAR     NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quality_results_run_date ON quality_results (run_date);
CREATE INDEX IF NOT EXISTS idx_quality_results_rule ON quality_results (rule_id);
