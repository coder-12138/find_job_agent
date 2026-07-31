CREATE TABLE candidate_profiles (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    archived_at TEXT
);

CREATE TABLE file_resources (
    id TEXT PRIMARY KEY,
    content_sha256 TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    original_name TEXT NOT NULL,
    storage_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE profile_versions (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    version_number INTEGER NOT NULL CHECK (version_number > 0),
    status TEXT NOT NULL CHECK (status IN ('draft', 'confirmed', 'archived')),
    profile_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (profile_id, version_number)
);

CREATE TABLE profile_version_sources (
    profile_version_id TEXT NOT NULL REFERENCES profile_versions(id),
    file_resource_id TEXT NOT NULL REFERENCES file_resources(id),
    PRIMARY KEY (profile_version_id, file_resource_id)
);

CREATE TABLE audit_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    occurred_at TEXT NOT NULL
);

CREATE INDEX audit_events_aggregate_sequence_idx
    ON audit_events(aggregate_type, aggregate_id, sequence);
