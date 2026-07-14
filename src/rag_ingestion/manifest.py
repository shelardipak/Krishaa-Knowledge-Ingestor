from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class IngestionManifest:
    def __init__(self, path: Path, data: dict[str, Any] | None = None) -> None:
        self.path = path
        self.data = data or {"version": 1, "files": {}}

    @classmethod
    def load(cls, path: Path) -> "IngestionManifest":
        if not path.exists():
            return cls(path)

        with path.open("r", encoding="utf-8") as file:
            return cls(path, json.load(file))

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump(self.data, file, indent=2, sort_keys=True)
            file.write("\n")

    def get_file(self, relative_path: str) -> dict[str, Any] | None:
        return self.data.setdefault("files", {}).get(relative_path)

    def is_current(self, relative_path: str, file_hash: str) -> bool:
        entry = self.get_file(relative_path)
        return bool(entry and entry.get("file_hash") == file_hash and entry.get("status") == "success")

    def mark_success(
        self,
        *,
        relative_path: str,
        file_hash: str,
        source_file: str,
        chunk_ids: list[str],
        extraction_json_path: str,
    ) -> None:
        self.data.setdefault("files", {})[relative_path] = {
            "status": "success",
            "file_hash": file_hash,
            "source_file": source_file,
            "chunk_ids": chunk_ids,
            "chunk_count": len(chunk_ids),
            "extraction_json_path": extraction_json_path,
            "ingested_at": datetime.now(UTC).isoformat(),
        }

    def mark_failed(self, *, relative_path: str, file_hash: str, error: str) -> None:
        previous_entry = self.get_file(relative_path) or {}
        failure_entry = {
            "status": "failed",
            "file_hash": file_hash,
            "error": error,
            "failed_at": datetime.now(UTC).isoformat(),
        }
        if previous_entry.get("chunk_ids"):
            failure_entry["chunk_ids"] = previous_entry["chunk_ids"]
            failure_entry["previous_status"] = previous_entry.get("status")

        self.data.setdefault("files", {})[relative_path] = {
            **failure_entry,
        }
