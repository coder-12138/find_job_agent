CREATE TABLE job_snapshots (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    source_url TEXT NOT NULL,
    title TEXT,
    company TEXT,
    snapshot_ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE applications (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    job_snapshot_id TEXT NOT NULL REFERENCES job_snapshots(id),
    profile_version_id TEXT NOT NULL REFERENCES profile_versions(id),
    state TEXT NOT NULL CHECK (state IN (
        'draft', 'ready_for_review', 'awaiting_login',
        'awaiting_user_submit', 'submitted', 'outcome_unknown',
        'failed', 'cancelled'
    )),
    state_reason TEXT,
    row_version INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    submitted_at TEXT
);

CREATE TABLE application_form_snapshots (
    application_id TEXT PRIMARY KEY REFERENCES applications(id),
    values_ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE application_materials (
    application_id TEXT NOT NULL REFERENCES applications(id),
    kind TEXT NOT NULL,
    file_resource_id TEXT NOT NULL REFERENCES file_resources(id),
    created_at TEXT NOT NULL,
    PRIMARY KEY (application_id, kind)
);

CREATE TABLE submission_receipts (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    outcome TEXT NOT NULL CHECK (outcome IN ('submitted', 'outcome_unknown', 'failed')),
    evidence_ciphertext BLOB NOT NULL,
    observed_at TEXT NOT NULL
);

CREATE TABLE browser_tasks (
    id TEXT PRIMARY KEY,
    application_id TEXT NOT NULL REFERENCES applications(id),
    state TEXT NOT NULL CHECK (state IN ('queued', 'running', 'waiting_user', 'completed', 'failed')),
    page_url TEXT,
    page_fingerprint TEXT,
    message TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE interaction_hints (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL,
    page_fingerprint TEXT NOT NULL,
    field_key TEXT NOT NULL,
    locator_strategy TEXT NOT NULL,
    locator_value TEXT NOT NULL,
    success_count INTEGER NOT NULL DEFAULT 0,
    failure_count INTEGER NOT NULL DEFAULT 0,
    review_status TEXT NOT NULL CHECK (review_status IN ('candidate', 'approved', 'disabled')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE (platform, page_fingerprint, field_key, locator_strategy, locator_value)
);

CREATE TABLE idempotency_keys (
    scope TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    resource_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, idempotency_key)
);

CREATE INDEX applications_state_idx ON applications(state, updated_at);
CREATE INDEX applications_profile_version_idx ON applications(profile_version_id);
CREATE INDEX browser_tasks_application_idx ON browser_tasks(application_id, created_at);
CREATE INDEX submission_receipts_application_idx ON submission_receipts(application_id, observed_at);
