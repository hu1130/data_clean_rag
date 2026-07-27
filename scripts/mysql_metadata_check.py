"""Check the route-A MySQL metadata database path.

This script does not initialize embeddings or a vector DB. It only verifies:
- config has metadata_db.enabled=true and metadata_db.type=mysql
- MySQL connection succeeds
- metadata tables can be created by the app adapter
- optional probe run can be written and queried back
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Dict

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.metadata_store import create_metadata_store


def load_config(path: str) -> Dict[str, Any]:
    config_path = Path(path)
    if not config_path.is_absolute():
        config_path = ROOT / config_path
    return yaml.safe_load(config_path.read_text(encoding="utf-8"))


def build_probe_payload(run_id: str) -> Dict[str, Any]:
    now = time.time()
    stats = {
        "input_count": 1,
        "cleaned_count": 1,
        "filtered_count": 1,
        "deduped_count": 1,
        "chunked_count": 1,
        "stored_count": 1,
        "started_at": now,
        "finished_at": now,
        "quality_summary": {
            "scored_count": 1,
            "rejected_count": 0,
            "average_score": 100,
            "reason_counts": {},
        },
        "processing_report": {
            "summary": {
                "input_count": 1,
                "cleaned_count": 1,
                "filtered_count": 1,
                "deduped_count": 1,
                "chunked_count": 1,
                "stored_count": 1,
            },
            "quality_summary": {
                "scored_count": 1,
                "rejected_count": 0,
                "average_score": 100,
                "reason_counts": {},
            },
            "parent_child": {
                "enabled": True,
                "parent_count": 1,
                "child_count": 1,
                "parent_context_chars": 1200,
            },
            "files": [
                {
                    "file_key": "mysql-probe.txt",
                    "filename": "mysql-probe.txt",
                    "file_type": ".txt",
                    "file_hash": "mysql-probe-hash",
                    "content_hash": "mysql-probe-hash",
                    "input_documents": 1,
                    "chunks": 1,
                    "chunk_ids": ["mysql-probe-chunk"],
                }
            ],
        },
    }
    chunks = [
        {
            "text": "route A mysql metadata probe chunk",
            "metadata": {
                "chunk_id": "mysql-probe-chunk",
                "child_id": "mysql-probe-chunk",
                "parent_id": "mysql-probe-parent",
                "file_key": "mysql-probe.txt",
                "filename": "mysql-probe.txt",
                "file_type": ".txt",
                "parent_type": "document",
                "parent_heading_path": "",
                "chunk_index": 0,
                "child_index": 0,
                "child_count": 1,
                "retrieval_level": "child",
                "retrieval_parent_child": True,
            },
        }
    ]
    return {"run_id": run_id, "stats": stats, "chunks": chunks}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify MySQL metadata_db connectivity and write path.")
    parser.add_argument("--config", default="config.mysql.example.yaml", help="Config file with metadata_db.type=mysql")
    parser.add_argument("--schema-only", action="store_true", help="Only connect and initialize schema; skip probe write")
    args = parser.parse_args()

    config = load_config(args.config)
    metadata_config = dict(config.get("metadata_db") or {})
    if not metadata_config.get("enabled"):
        raise SystemExit("metadata_db.enabled must be true for this check")
    if metadata_config.get("type") != "mysql":
        raise SystemExit("metadata_db.type must be mysql for this check")

    store = create_metadata_store(metadata_config)
    result: Dict[str, Any] = {
        "passed": False,
        "config": args.config,
        "schema_initialized": True,
        "write_probe": not args.schema_only,
        "store": store.health(),
    }

    try:
        if not args.schema_only:
            run_id = f"mysql-probe-{uuid.uuid4()}"
            payload = build_probe_payload(run_id)
            stored_run_id = store.record_processing_run(
                payload["stats"],
                payload["chunks"],
                run_id=payload["run_id"],
            )
            run = store.get_run(stored_run_id)
            result.update({
                "run_id": stored_run_id,
                "run_found": bool(run),
                "persisted_chunk_count": len((run or {}).get("chunks", [])),
            })
            result["passed"] = bool(run and len(run.get("chunks", [])) == 1)
        else:
            result["passed"] = True
    finally:
        store.close()

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
