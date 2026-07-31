CREATE TABLE resume_extractions (
    file_resource_id TEXT PRIMARY KEY REFERENCES file_resources(id),
    extractor_version TEXT NOT NULL,
    extraction_ciphertext BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX resume_extractions_updated_idx
    ON resume_extractions(updated_at);
