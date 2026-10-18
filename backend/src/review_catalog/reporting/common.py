from __future__ import annotations

import json
import math
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import duckdb


def fetch_dicts(connection: duckdb.DuckDBPyConnection, query: str, params=None) -> list[dict]:
    cursor = connection.execute(query, params or [])
    columns = [item[0] for item in cursor.description]
    return [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]


def collapse_sentiments(values: set[str]) -> str:
    known = values - {"unknown"}
    if not known:
        return "unknown"
    if len(known) == 1:
        return next(iter(known))
    return "mixed"


def wilson_interval(
    successes: int, total: int, z: float = 1.959963984540054
) -> tuple[float, float]:
    if total == 0:
        return 0.0, 0.0
    proportion = successes / total
    denominator = 1 + z * z / total
    centre = proportion + z * z / (2 * total)
    margin = z * math.sqrt((proportion * (1 - proportion) + z * z / (4 * total)) / total)
    return (max(0.0, (centre - margin) / denominator), min(1.0, (centre + margin) / denominator))


def atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        temporary.write_text(text, encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def write_report_pair(
    output_dir: Path, stem: str, payload: dict, markdown: str
) -> tuple[Path, Path]:
    json_path = output_dir / f"{stem}.json"
    markdown_path = output_dir / f"{stem}.md"
    atomic_write_text(json_path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    atomic_write_text(markdown_path, markdown)
    return json_path, markdown_path


def report_source(
    *, release_id: str, generated_at: datetime, versions: dict[str, Any]
) -> dict[str, Any]:
    """Expose catalog-release lineage in the source report's metadata shape."""
    mapping = versions["mapping_table"]
    embedding = versions["embedding_model"]
    prompt = versions["opinion_unit_prompt"]
    mapping_id = str(mapping["id"])
    mapping_sha = str(mapping.get("content_sha256") or "")
    normalization_run_id = mapping.get("normalization_run_id") or mapping_id.removeprefix(
        "mapping-table-"
    )
    return {
        "experiment": "D",
        "run_id": normalization_run_id,
        "created_at_local": generated_at.astimezone(ZoneInfo("Asia/Seoul")).isoformat(),
        "scope": "catalog_release_full_snapshot",
        "sampling_used": False,
        "run_manifest_sha256": mapping_sha,
        "normalization": {
            "embedding_model_id": embedding.get("version") or embedding["id"],
            "normalization_version": mapping.get("normalization_version")
            or mapping.get("version")
            or mapping_id,
            "normalization_run_id": normalization_run_id,
            "normalization_config_sha256": mapping.get("normalization_config_sha256"),
            "mapping_distance_metric": "cosine",
        },
        "input_sha256": {
            "opinion_unit_prompt": prompt.get("content_sha256") or "",
            "mapping_table": mapping_sha,
        },
        "catalog_release": {
            "release_id": release_id,
            "report_generator_version": versions["report_generator"].get("version")
            or versions["report_generator"]["id"],
        },
    }
