-- Route A metadata database schema for data_clean_rag.
-- MySQL stores business metadata and audit records; vector search remains in vector_db.
--
-- Run as a privileged MySQL user:
--   mysql -u root -p < deploy/mysql/metadata_schema.sql
--
-- Optional app user setup, replace the password before running:
--   CREATE USER IF NOT EXISTS 'data_clean_rag'@'%' IDENTIFIED BY 'change-me';
--   GRANT SELECT, INSERT, UPDATE, DELETE, CREATE, INDEX, ALTER
--     ON data_clean_rag.* TO 'data_clean_rag'@'%';
--   FLUSH PRIVILEGES;

CREATE DATABASE IF NOT EXISTS data_clean_rag
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE data_clean_rag;

CREATE TABLE IF NOT EXISTS metadata_processing_runs (
  run_id VARCHAR(128) PRIMARY KEY,
  status VARCHAR(32) NOT NULL,
  started_at DOUBLE,
  finished_at DOUBLE,
  input_count INT DEFAULT 0,
  cleaned_count INT DEFAULT 0,
  filtered_count INT DEFAULT 0,
  deduped_count INT DEFAULT 0,
  chunked_count INT DEFAULT 0,
  stored_count INT DEFAULT 0,
  quality_summary_json LONGTEXT,
  processing_report_json LONGTEXT,
  metadata_json LONGTEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS metadata_files (
  file_key VARCHAR(512) PRIMARY KEY,
  filename VARCHAR(512),
  source_file VARCHAR(1024),
  file_type VARCHAR(64),
  file_hash VARCHAR(128),
  content_hash VARCHAR(128),
  file_size_bytes BIGINT,
  document_count INT DEFAULT 0,
  chunk_count INT DEFAULT 0,
  status VARCHAR(32),
  first_seen_at DOUBLE,
  updated_at DOUBLE,
  last_processed_at DOUBLE,
  metadata_json LONGTEXT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS metadata_chunks (
  chunk_id VARCHAR(128) PRIMARY KEY,
  run_id VARCHAR(128),
  parent_id VARCHAR(128),
  file_key VARCHAR(512),
  filename VARCHAR(512),
  parent_type VARCHAR(64),
  parent_heading_path VARCHAR(1024),
  chunk_index INT DEFAULT 0,
  child_index INT DEFAULT 0,
  child_count INT DEFAULT 1,
  text_preview TEXT,
  metadata_json LONGTEXT,
  created_at DOUBLE,
  KEY idx_metadata_chunks_run_id (run_id),
  KEY idx_metadata_chunks_file_key (file_key),
  KEY idx_metadata_chunks_parent_id (parent_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
