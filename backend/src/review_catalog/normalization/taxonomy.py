from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from review_catalog.pipeline.artifacts import canonical_sha256


@dataclass(frozen=True)
class TaxonomyManifest:
    """Immutable identity of one clustering-derived mapping-table bundle."""

    mapping_table_version_id: str
    normalization_version: str
    normalization_run_id: str
    normalization_config_sha256: str
    embedding_model_id: str
    embedding_model_artifact_sha256: str
    source_prompt_version_id: str
    source_prompt_sha256: str
    source_extraction_model_version_id: str
    source_extraction_backend: str
    source_extraction_model: str
    source_extraction_reasoning_effort: str
    metric: str
    linkage: str
    aspect_distance_threshold: float
    status_distance_threshold: float
    counts: dict[str, int]
    artifacts: dict[str, str]
    content_sha256: str


def load_taxonomy_manifest(path: Path) -> TaxonomyManifest:
    payload_bytes = path.read_bytes()
    payload: dict[str, Any] = json.loads(payload_bytes)
    required = {
        "schema_version",
        "mapping_table_version_id",
        "normalization_version",
        "normalization_run_id",
        "normalization_config_sha256",
        "embedding_model_id",
        "embedding_model_artifact_sha256",
        "source_prompt_version_id",
        "source_prompt_sha256",
        "source_extraction_model_version_id",
        "source_extraction_backend",
        "source_extraction_model",
        "source_extraction_reasoning_effort",
        "metric",
        "linkage",
        "aspect_distance_threshold",
        "status_distance_threshold",
        "counts",
        "artifacts",
    }
    if set(payload) != required:
        raise ValueError(
            "taxonomy manifest fields differ: "
            f"missing={sorted(required - set(payload))}, extra={sorted(set(payload) - required)}"
        )
    if payload["metric"] != "cosine" or payload["linkage"] != "complete":
        raise ValueError("only the verified cosine complete-linkage taxonomy is supported")
    return TaxonomyManifest(
        mapping_table_version_id=str(payload["mapping_table_version_id"]),
        normalization_version=str(payload["normalization_version"]),
        normalization_run_id=str(payload["normalization_run_id"]),
        normalization_config_sha256=str(payload["normalization_config_sha256"]),
        embedding_model_id=str(payload["embedding_model_id"]),
        embedding_model_artifact_sha256=str(payload["embedding_model_artifact_sha256"]),
        source_prompt_version_id=str(payload["source_prompt_version_id"]),
        source_prompt_sha256=str(payload["source_prompt_sha256"]),
        source_extraction_model_version_id=str(payload["source_extraction_model_version_id"]),
        source_extraction_backend=str(payload["source_extraction_backend"]),
        source_extraction_model=str(payload["source_extraction_model"]),
        source_extraction_reasoning_effort=str(payload["source_extraction_reasoning_effort"]),
        metric=str(payload["metric"]),
        linkage=str(payload["linkage"]),
        aspect_distance_threshold=float(payload["aspect_distance_threshold"]),
        status_distance_threshold=float(payload["status_distance_threshold"]),
        counts={str(key): int(value) for key, value in payload["counts"].items()},
        artifacts={str(key): str(value) for key, value in payload["artifacts"].items()},
        content_sha256=hashlib.sha256(payload_bytes).hexdigest(),
    )


def load_normalization_config(path: Path) -> dict[str, Any]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    required = {
        "normalization_version",
        "embedding_model_id",
        "filters",
        "clustering",
        "canonical_label",
    }
    if not isinstance(config, dict) or set(config) != required:
        raise ValueError("normalization config must contain only the runtime settings")
    return config


def verify_normalization_config(config: dict[str, Any], manifest: TaxonomyManifest) -> None:
    if config["embedding_model_id"] != manifest.embedding_model_id:
        raise ValueError("active mapping table and configured embedding model differ")
    if canonical_sha256(config) != manifest.normalization_config_sha256:
        raise ValueError("configured normalization parameters differ from the active taxonomy")
