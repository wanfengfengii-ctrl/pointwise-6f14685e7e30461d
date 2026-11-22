BEGIN IMMEDIATE;

CREATE TABLE IF NOT EXISTS seams (
    seam_id TEXT PRIMARY KEY NOT NULL,
    description TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS payloads (
    kind TEXT NOT NULL CHECK (kind IN ('scan', 'patch')),
    target_key TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    pixels BLOB,
    PRIMARY KEY (kind, target_key)
);
CREATE TABLE IF NOT EXISTS scans (
    scan_id TEXT PRIMARY KEY NOT NULL,
    capture_sheet TEXT NOT NULL,
    initial_seam TEXT REFERENCES seams(seam_id)
);
CREATE TABLE IF NOT EXISTS attribution_revisions (
    revision_id TEXT PRIMARY KEY NOT NULL
);
CREATE TABLE IF NOT EXISTS scan_attributions (
    revision_id TEXT NOT NULL REFERENCES attribution_revisions(revision_id),
    scan_id TEXT NOT NULL REFERENCES scans(scan_id),
    seam_id TEXT NOT NULL REFERENCES seams(seam_id),
    PRIMARY KEY (revision_id, scan_id)
);
CREATE TABLE IF NOT EXISTS patch_revisions (
    revision_id TEXT PRIMARY KEY NOT NULL,
    patch_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    superseded INTEGER NOT NULL DEFAULT 0 CHECK (superseded IN (0, 1)),
    retired INTEGER NOT NULL DEFAULT 0 CHECK (retired IN (0, 1)),
    CHECK (retired <= superseded)
);
CREATE UNIQUE INDEX IF NOT EXISTS one_current_patch_revision
    ON patch_revisions(patch_id) WHERE superseded = 0;
CREATE TABLE IF NOT EXISTS patch_parents (
    revision_id TEXT NOT NULL REFERENCES patch_revisions(revision_id),
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('scan', 'patch')),
    parent_key TEXT NOT NULL,
    PRIMARY KEY (revision_id, position),
    UNIQUE (revision_id, kind, parent_key)
);
CREATE TABLE IF NOT EXISTS work_orders (
    training_id TEXT PRIMARY KEY NOT NULL,
    closed INTEGER NOT NULL DEFAULT 0 CHECK (closed IN (0, 1))
);
CREATE TABLE IF NOT EXISTS work_order_materials (
    training_id TEXT NOT NULL REFERENCES work_orders(training_id),
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('scan', 'patch', 'definition')),
    target_key TEXT NOT NULL,
    PRIMARY KEY (training_id, position),
    UNIQUE (training_id, kind, target_key)
);
CREATE TABLE IF NOT EXISTS material_holds (
    kind TEXT NOT NULL CHECK (kind IN ('scan', 'patch', 'definition')),
    target_key TEXT NOT NULL,
    training_id TEXT NOT NULL REFERENCES work_orders(training_id),
    PRIMARY KEY (kind, target_key, training_id)
);
CREATE INDEX IF NOT EXISTS material_holds_by_order ON material_holds(training_id);
CREATE TABLE IF NOT EXISTS training_receipts (
    training_id TEXT PRIMARY KEY NOT NULL
);
CREATE TABLE IF NOT EXISTS training_inputs (
    training_id TEXT NOT NULL REFERENCES training_receipts(training_id),
    position INTEGER NOT NULL,
    revision_id TEXT NOT NULL REFERENCES patch_revisions(revision_id),
    PRIMARY KEY (training_id, position),
    UNIQUE (training_id, revision_id)
);
CREATE TABLE IF NOT EXISTS revision_parent_evidence (
    revision_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('scan', 'patch')),
    parent_key TEXT NOT NULL,
    PRIMARY KEY (revision_id, position)
);
CREATE TABLE IF NOT EXISTS frozen_batches (
    batch_id TEXT PRIMARY KEY NOT NULL,
    first_training TEXT NOT NULL REFERENCES training_receipts(training_id),
    second_training TEXT NOT NULL REFERENCES training_receipts(training_id),
    CHECK (first_training <> second_training)
);
CREATE TABLE IF NOT EXISTS frozen_rows (
    batch_id TEXT NOT NULL REFERENCES frozen_batches(batch_id),
    position INTEGER NOT NULL,
    piece_id TEXT NOT NULL,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id),
    actual INTEGER NOT NULL CHECK (actual IN (0, 1)),
    first_p TEXT NOT NULL,
    second_p TEXT NOT NULL,
    PRIMARY KEY (batch_id, position),
    UNIQUE (batch_id, piece_id)
);
CREATE TABLE IF NOT EXISTS label_records (
    batch_id TEXT NOT NULL,
    piece_id TEXT NOT NULL,
    actual INTEGER NOT NULL CHECK (actual IN (0, 1)),
    PRIMARY KEY (batch_id, piece_id),
    FOREIGN KEY (batch_id, piece_id) REFERENCES frozen_rows(batch_id, piece_id)
);
CREATE TABLE IF NOT EXISTS prediction_groups (
    batch_id TEXT NOT NULL REFERENCES frozen_batches(batch_id),
    model_position INTEGER NOT NULL CHECK (model_position IN (0, 1)),
    training_id TEXT NOT NULL REFERENCES training_receipts(training_id),
    PRIMARY KEY (batch_id, model_position)
);
CREATE TABLE IF NOT EXISTS prediction_records (
    batch_id TEXT NOT NULL,
    model_position INTEGER NOT NULL,
    submitted_position INTEGER NOT NULL,
    piece_id TEXT NOT NULL,
    probability TEXT NOT NULL,
    PRIMARY KEY (batch_id, model_position, submitted_position),
    UNIQUE (batch_id, model_position, piece_id),
    FOREIGN KEY (batch_id, model_position) REFERENCES prediction_groups(batch_id, model_position),
    FOREIGN KEY (batch_id, piece_id) REFERENCES frozen_rows(batch_id, piece_id)
);
CREATE TABLE IF NOT EXISTS signed_reports (
    report_id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES frozen_batches(batch_id),
    first_training TEXT NOT NULL REFERENCES training_receipts(training_id),
    second_training TEXT NOT NULL REFERENCES training_receipts(training_id),
    mean_difference TEXT
);
CREATE TABLE IF NOT EXISTS report_rows (
    report_id INTEGER NOT NULL REFERENCES signed_reports(report_id),
    position INTEGER NOT NULL,
    piece_id TEXT NOT NULL,
    scan_id TEXT NOT NULL REFERENCES scans(scan_id),
    actual INTEGER NOT NULL CHECK (actual IN (0, 1)),
    first_p TEXT NOT NULL,
    second_p TEXT NOT NULL,
    first_error TEXT NOT NULL,
    second_error TEXT NOT NULL,
    difference TEXT NOT NULL,
    PRIMARY KEY (report_id, position)
);
CREATE TABLE IF NOT EXISTS issue_receipts (
    report_id INTEGER PRIMARY KEY REFERENCES signed_reports(report_id),
    receipt_id TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS retirement_receipts (
    kind TEXT NOT NULL CHECK (kind IN ('scan', 'patch', 'definition')),
    target_key TEXT NOT NULL,
    cutoff INTEGER NOT NULL,
    PRIMARY KEY (kind, target_key)
);
CREATE TABLE IF NOT EXISTS clean_reports (
    report_id INTEGER PRIMARY KEY,
    batch_id TEXT NOT NULL REFERENCES frozen_batches(batch_id),
    first_training TEXT NOT NULL REFERENCES training_receipts(training_id),
    second_training TEXT NOT NULL REFERENCES training_receipts(training_id),
    attribution_id TEXT NOT NULL REFERENCES attribution_revisions(revision_id),
    mean_difference TEXT,
    CHECK (first_training <> second_training)
);
CREATE TABLE IF NOT EXISTS clean_report_pieces (
    report_id INTEGER NOT NULL REFERENCES clean_reports(report_id),
    position INTEGER NOT NULL,
    piece_id TEXT NOT NULL,
    scan_id TEXT NOT NULL,
    seam_id TEXT NOT NULL,
    included INTEGER NOT NULL CHECK (included IN (0, 1)),
    first_p TEXT NOT NULL,
    second_p TEXT NOT NULL,
    difference TEXT,
    PRIMARY KEY (report_id, position)
);
CREATE TABLE IF NOT EXISTS clean_report_matches (
    report_id INTEGER NOT NULL REFERENCES clean_reports(report_id),
    position INTEGER NOT NULL,
    model_position INTEGER NOT NULL CHECK (model_position IN (0, 1)),
    training_id TEXT NOT NULL,
    PRIMARY KEY (report_id, position, model_position)
);
CREATE TABLE IF NOT EXISTS clean_report_scans (
    report_id INTEGER NOT NULL REFERENCES clean_reports(report_id),
    model_position INTEGER NOT NULL CHECK (model_position IN (0, 1)),
    scan_position INTEGER NOT NULL,
    scan_id TEXT NOT NULL,
    PRIMARY KEY (report_id, model_position, scan_position)
);
CREATE TABLE IF NOT EXISTS clean_report_receipts (
    report_id INTEGER PRIMARY KEY REFERENCES clean_reports(report_id),
    receipt_id TEXT NOT NULL UNIQUE
);

COMMIT;
