ALTER TABLE candidate_profiles
    ADD COLUMN row_version INTEGER NOT NULL DEFAULT 0;

ALTER TABLE profile_versions
    ADD COLUMN source_file_resource_id TEXT REFERENCES file_resources(id);

ALTER TABLE profile_versions
    ADD COLUMN profile_ciphertext BLOB;

CREATE TABLE profile_change_proposals (
    id TEXT PRIMARY KEY,
    profile_id TEXT NOT NULL REFERENCES candidate_profiles(id),
    base_version_id TEXT NOT NULL REFERENCES profile_versions(id),
    source_file_resource_id TEXT NOT NULL REFERENCES file_resources(id),
    status TEXT NOT NULL CHECK (status IN ('pending', 'accepted', 'discarded')),
    proposed_fields_ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX profile_change_proposals_profile_idx
    ON profile_change_proposals(profile_id, status, created_at);
