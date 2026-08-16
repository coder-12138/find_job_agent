ALTER TABLE candidate_profiles
    ADD COLUMN active_version_id TEXT REFERENCES profile_versions(id);

CREATE INDEX candidate_profiles_active_version_idx
    ON candidate_profiles(active_version_id);
