from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from review_catalog.normalization.taxonomy import load_taxonomy_manifest
from review_catalog.settings import Settings


def test_local_outputs_are_separate_from_input_directories(project_root, tmp_path, monkeypatch):
    for field in ("CATALOG_DATA_ROOT", "BOOTSTRAP_SOURCE_ROOT", "INGESTION_INBOX_PATH"):
        monkeypatch.delenv(f"REVIEW_CATALOG_{field}", raising=False)
    monkeypatch.chdir(tmp_path)
    defaults = Settings(_env_file=None)
    assert defaults.catalog_data_root == project_root / "data/runtime"
    assert defaults.bootstrap_source_root == project_root / "data/migration/source"
    assert defaults.ingestion_inbox_path == project_root / "data/ingestion/inbox_reviews.json"
    assert defaults.bootstrap_source_root.is_dir()
    assert defaults.ingestion_inbox_path.is_file()

    settings = Settings(catalog_data_root=tmp_path / "data/runtime", _env_file=None)
    settings.ensure_directories()
    assert all(
        path.is_dir()
        for path in (
            settings.work_root,
            settings.release_staging_root,
            settings.release_root,
            settings.writer_lock_path.parent,
        )
    )
    assert not (tmp_path / "data/migration").exists()
    assert not (tmp_path / "data/ingestion").exists()


def test_git_includes_nested_bootstrap_inputs_and_excludes_runtime(project_root):
    manifest = load_taxonomy_manifest(project_root / "config/taxonomy/2026-10-05_142933.json")
    paths = [
        str(path.relative_to(project_root))
        for path in (project_root / "data/migration").rglob("*")
        if path.is_file()
    ]
    assert len(paths) == len(manifest.artifacts) == 7
    paths += ["data/ingestion/inbox_reviews.json"]
    excluded = [
        "data/runtime/releases/release-test/catalog.duckdb",
        "data/runtime/work/run-test/versions.json",
        "data/unclassified/review.json",
    ]
    result = subprocess.run(
        ["git", "check-ignore", "--no-index", "--stdin"],
        input="\n".join(paths + excluded) + "\n",
        cwd=project_root,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert set(result.stdout.splitlines()) == set(excluded)


def test_compose_inputs_are_readonly_and_existing_runtime_volume_is_preserved(project_root):
    compose = yaml.safe_load((project_root / "docker-compose.yml").read_text())
    worker = compose["x-airflow-common"]
    environment = worker["environment"]
    mounts = {
        source: (Path(destination), mode)
        for source, destination, mode in (
            mount.split(":") for mount in worker["volumes"] if mount.count(":") == 2
        )
    }
    for name, env_field, relative_file in (
        ("migration", "REVIEW_CATALOG_BOOTSTRAP_SOURCE_ROOT", "source"),
        ("ingestion", "REVIEW_CATALOG_INGESTION_INBOX_PATH", "inbox_reviews.json"),
    ):
        source = f"./data/{name}"
        destination, mode = mounts[source]
        assert mode == "ro"
        assert Path(environment[env_field]) == destination / relative_file
        assert (project_root / source / relative_file).exists()

    assert environment["REVIEW_CATALOG_CATALOG_DATA_ROOT"] == "/data/catalog"
    for service in (worker, compose["services"]["api"], compose["services"]["catalog-init"]):
        assert "catalog_data:/data/catalog" in service["volumes"]
    assert "catalog_data" in compose["volumes"]
    assert not any("./data/runtime:" in mount for mount in worker["volumes"])
