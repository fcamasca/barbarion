"""SQL explicito de persistencia para la ingesta H2."""

INGESTION_SCHEMA_STATEMENTS: tuple[str, ...] = (
    """
    CREATE TABLE IF NOT EXISTS ingestion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        domain TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('incremental', 'full')),
        status TEXT NOT NULL CHECK (
            status IN (
                'running',
                'completed',
                'completed_with_errors',
                'failed',
                'interrupted'
            )
        ),
        roots_json TEXT NOT NULL,
        config_sha256 TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        discovered_files INTEGER NOT NULL DEFAULT 0 CHECK (discovered_files >= 0),
        processed_files INTEGER NOT NULL DEFAULT 0 CHECK (processed_files >= 0),
        unchanged_files INTEGER NOT NULL DEFAULT 0 CHECK (unchanged_files >= 0),
        skipped_files INTEGER NOT NULL DEFAULT 0 CHECK (skipped_files >= 0),
        deleted_files INTEGER NOT NULL DEFAULT 0 CHECK (deleted_files >= 0),
        error_count INTEGER NOT NULL DEFAULT 0 CHECK (error_count >= 0),
        source_bytes INTEGER NOT NULL DEFAULT 0 CHECK (source_bytes >= 0),
        processed_bytes INTEGER NOT NULL DEFAULT 0 CHECK (processed_bytes >= 0),
        chunk_count INTEGER NOT NULL DEFAULT 0 CHECK (chunk_count >= 0),
        duration_ms INTEGER CHECK (duration_ms IS NULL OR duration_ms >= 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ingestion_runs_started_at
    ON ingestion_runs(started_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_ingestion_runs_status
    ON ingestion_runs(status)
    """,
    """
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY,
        domain TEXT NOT NULL,
        source_root TEXT NOT NULL,
        relative_path TEXT NOT NULL,
        extension TEXT NOT NULL,
        artifact_kind TEXT NOT NULL,
        media_type TEXT NOT NULL,
        size_bytes INTEGER NOT NULL CHECK (size_bytes >= 0),
        modified_at_ns INTEGER NOT NULL CHECK (modified_at_ns >= 0),
        sha256 TEXT,
        fingerprint_version INTEGER NOT NULL DEFAULT 1 CHECK (
            fingerprint_version > 0
        ),
        processing_signature TEXT,
        parser_id TEXT,
        parser_version TEXT,
        encoding TEXT,
        status TEXT NOT NULL CHECK (
            status IN ('pending', 'processed', 'skipped', 'error', 'deleted')
        ),
        skip_reason TEXT,
        first_seen_run_id INTEGER NOT NULL REFERENCES ingestion_runs(id),
        last_seen_run_id INTEGER NOT NULL REFERENCES ingestion_runs(id),
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        processed_at TEXT,
        deleted_at TEXT,
        UNIQUE(domain, source_root, relative_path)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_status
    ON files(status)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_artifact_kind
    ON files(artifact_kind)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_sha256
    ON files(sha256)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_last_seen_run_id
    ON files(last_seen_run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_files_source_root_last_seen_run_id
    ON files(source_root, last_seen_run_id)
    """,
    """
    CREATE TABLE IF NOT EXISTS documents (
        id INTEGER PRIMARY KEY,
        file_id INTEGER NOT NULL UNIQUE REFERENCES files(id) ON DELETE CASCADE,
        source_sha256 TEXT NOT NULL,
        parser_id TEXT NOT NULL,
        parser_version TEXT NOT NULL,
        normalizer_version TEXT NOT NULL,
        title TEXT,
        normalized_text TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        metadata_json TEXT NOT NULL,
        warnings_json TEXT NOT NULL,
        extracted_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_documents_content_sha256
    ON documents(content_sha256)
    """,
    """
    CREATE TABLE IF NOT EXISTS chunks (
        id TEXT PRIMARY KEY,
        document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
        ordinal INTEGER NOT NULL CHECK (ordinal >= 0),
        chunk_type TEXT NOT NULL,
        content TEXT NOT NULL,
        content_sha256 TEXT NOT NULL,
        start_line INTEGER CHECK (start_line IS NULL OR start_line > 0),
        end_line INTEGER CHECK (end_line IS NULL OR end_line > 0),
        start_char INTEGER CHECK (start_char IS NULL OR start_char > 0),
        end_char INTEGER CHECK (end_char IS NULL OR end_char > 0),
        page_start INTEGER CHECK (page_start IS NULL OR page_start > 0),
        page_end INTEGER CHECK (page_end IS NULL OR page_end > 0),
        object_type TEXT,
        object_name TEXT,
        metadata_json TEXT NOT NULL,
        chunker_version TEXT NOT NULL,
        created_at TEXT NOT NULL,
        CHECK ((start_line IS NULL AND end_line IS NULL) OR end_line >= start_line),
        CHECK ((start_char IS NULL AND end_char IS NULL) OR end_char >= start_char),
        CHECK ((page_start IS NULL AND page_end IS NULL) OR page_end >= page_start),
        UNIQUE(document_id, ordinal, chunker_version)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_document_ordinal
    ON chunks(document_id, ordinal)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_object
    ON chunks(object_type, object_name)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_chunks_content_sha256
    ON chunks(content_sha256)
    """,
    """
    CREATE TABLE IF NOT EXISTS errors (
        id INTEGER PRIMARY KEY,
        run_id INTEGER NOT NULL REFERENCES ingestion_runs(id) ON DELETE CASCADE,
        file_id INTEGER REFERENCES files(id) ON DELETE SET NULL,
        stage TEXT NOT NULL,
        error_code TEXT NOT NULL,
        message TEXT NOT NULL,
        exception_type TEXT,
        recoverable INTEGER NOT NULL CHECK (recoverable IN (0, 1)),
        details_json TEXT NOT NULL,
        occurred_at TEXT NOT NULL
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_errors_run_id
    ON errors(run_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_errors_file_id
    ON errors(file_id)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_errors_error_code
    ON errors(error_code)
    """,
)

