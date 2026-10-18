from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime

import duckdb
import numpy as np
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from review_catalog.api import routes
from review_catalog.api.schemas import DemoSubmissionRequest
from review_catalog.db.models import Base, CatalogRelease, PipelineRun, ReportArtifact
from review_catalog.extraction.contracts import ExtractionResult, OpinionUnit
from review_catalog.normalization.taxonomy import (
    load_normalization_config,
    load_taxonomy_manifest,
    verify_normalization_config,
)
from review_catalog.pipeline import reclustering, stages
from review_catalog.pipeline.artifacts import atomic_write_json, read_json, sha256_file
from review_catalog.pipeline.catalog_store import SCHEMA_SQL
from review_catalog.services import release
from review_catalog.settings import Settings


@pytest.fixture
def runtime(tmp_path, project_root, monkeypatch):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'metadata.sqlite'}",
        catalog_data_root=tmp_path / "data/runtime",
        taxonomy_manifest_path=project_root / "config/taxonomy/2026-10-05_142933.json",
        normalization_config_path=project_root / "config/normalization/2026-10-05_142933.yaml",
        bootstrap_source_root=project_root / "data/migration/source",
        ingestion_inbox_path=tmp_path / "data/ingestion/inbox_reviews.json",
    )
    settings.ensure_directories()
    atomic_write_json(settings.ingestion_inbox_path, [])
    engine = create_engine(settings.database_url)
    Base.metadata.create_all(engine)
    # Match production PostgreSQL partial unique indexes in the SQLite test store.
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP INDEX uq_one_active_component_version")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_one_active_component_version "
            "ON component_versions(component_type) WHERE is_active = 1"
        )
        connection.exec_driver_sql("DROP INDEX uq_current_catalog_release")
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_current_catalog_release "
            "ON catalog_releases(is_current) WHERE is_current = 1"
        )
    sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    for module in (stages, reclustering, release):
        monkeypatch.setattr(module, "SessionLocal", sessions)
        monkeypatch.setattr(module, "get_settings", lambda: settings)
    monkeypatch.setattr(stages, "create_schema", lambda: None)
    yield settings, sessions
    engine.dispose()


def _ingest(run_id):
    versions = stages.resolve_versions_stage(run_id)
    staged = stages.stage_reviews(run_id)
    deduplicated = stages.deduplicate_reviews(run_id, staged)
    extracted = stages.extract_opinion_units(run_id, deduplicated, versions)
    validated = stages.validate_opinion_units(run_id, extracted)
    mapped = stages.map_to_active_taxonomy(run_id, validated, versions)
    delta = stages.prepare_catalog_delta(run_id, deduplicated, mapped, versions)
    manifest = stages.commit_catalog_delta_stage(run_id, delta)
    stages.check_taxonomy_rebuild_condition(run_id, manifest)
    return release.finalize_catalog_release(run_id)


def test_bootstrap_publish_demo_and_file_inbox(runtime, monkeypatch):
    settings, sessions = runtime
    run_id = stages.register_run(dag_run_id="bootstrap-test", conf={}, trigger_type="manual")
    first_release_id = _ingest(run_id)
    first_snapshot = settings.release_root / first_release_id / "catalog.duckdb"
    first_sha = sha256_file(first_snapshot)
    manifest = load_taxonomy_manifest(settings.taxonomy_manifest_path)
    report_json = next(
        (settings.release_root / first_release_id / "reports/static").glob(
            "*/static_catalog_report.json"
        )
    )
    report = read_json(report_json)
    assert (
        report["source"]["normalization"]["normalization_run_id"] == manifest.normalization_run_id
    )
    assert (
        report["source"]["normalization"]["normalization_config_sha256"]
        == manifest.normalization_config_sha256
    )
    assert "human_evaluation" not in report
    assert "human_evaluation" not in report["source"]

    with sessions() as session:
        products = routes.products(session)
        assert len(products) == 9
        assert sum(product["review_count"] for product in products) == 1609
        assert len(session.scalars(select(ReportArtifact)).all()) == 9
        assert routes.product_report(products[0]["product_id"], session).body
    with duckdb.connect(str(first_snapshot), read_only=True) as connection:
        assert connection.execute("SELECT count(*) FROM opinion_units").fetchone()[0] == 5033
        assert connection.execute("SELECT count(*) FROM source_artifacts").fetchone()[0] == 7
        assert (
            connection.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_name = 'representative_attributes'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT DISTINCT source FROM reviews").fetchall() == [
            ("source_parquet",)
        ]

    class FakeAirflowClient:
        def __init__(self, _settings):
            pass

        def trigger_catalog_ingestion(self, **_kwargs):
            return "demo-test"

    class FakeExtractor:
        def extract(self, reviews):
            return [
                ExtractionResult(
                    review=review,
                    opinion_units=[
                        OpinionUnit(
                            raw_aspect="화질",
                            raw_status="깔끔함",
                            excerpt=review.review,
                            opinion="화질이 깔끔함",
                            sentiment="positive",
                        )
                    ],
                    prompt_version_id=manifest.source_prompt_version_id,
                    model_version_id=settings.extraction_model,
                    raw_response_sha256="a" * 64,
                )
                for review in reviews
            ]

    class ExactOnlyEmbedder:
        def encode(self, _texts):
            raise AssertionError("exact mapping must not request an embedding")

    manifest = load_taxonomy_manifest(settings.taxonomy_manifest_path)
    monkeypatch.setattr(routes, "AirflowClient", FakeAirflowClient)
    monkeypatch.setattr(stages, "build_extractor", lambda *_args, **_kwargs: FakeExtractor())
    monkeypatch.setattr(stages, "build_embedder", lambda _settings: ExactOnlyEmbedder())
    with sessions() as session:
        accepted = routes.create_demo_submission(
            DemoSubmissionRequest(product_id=products[0]["product_id"], reviews=["화질이 깔끔함"]),
            session,
            settings,
        )
        conf = dict(session.get(PipelineRun, accepted.pipeline_run_id).conf_json)
    stages.register_run(
        dag_run_id="demo-test",
        conf={**conf, "pipeline_run_id": accepted.pipeline_run_id},
        trigger_type="manual",
    )
    second_release_id = _ingest(accepted.pipeline_run_id)
    assert second_release_id != first_release_id
    assert sha256_file(first_snapshot) == first_sha
    with sessions() as session:
        response = routes.demo_submission(accepted.submission_id, session)
        assert response["state"] == "completed"
        assert response["results"][0]["opinion_units"][0]["mapping_state"] == "mapped_exact"
        assert response["results"][0]["proposal_markdown"]
        assert (
            session.get(CatalogRelease, second_release_id).previous_release_id == first_release_id
        )
        assert len(session.scalars(select(ReportArtifact)).all()) == 19

    # Read a file-based batch from the new input directory, keeping runtime output separate.
    inbox_review = {
        "source_review_id": "inbox-1",
        "product_id": products[0]["product_id"],
        "product_name": products[0]["product_name"],
        "review_text": "화질이 깔끔함. 화면이 선명해요.",
    }
    inbox_batch = [inbox_review, {**inbox_review, "source_review_id": "inbox-duplicate"}]
    atomic_write_json(settings.ingestion_inbox_path, inbox_batch)
    file_run = stages.register_run(dag_run_id="inbox-test", conf={}, trigger_type="manual")
    _ingest(file_run)
    with sessions() as session:
        run = session.get(PipelineRun, file_run)
        assert run.staged_review_count == 2
        assert run.committed_review_count == 1
        assert sum(product["review_count"] for product in routes.products(session)) == 1611
    assert read_json(settings.ingestion_inbox_path) == inbox_batch
    assert sha256_file(first_snapshot) == first_sha

    retry_run = stages.register_run(dag_run_id="inbox-replay", conf={}, trigger_type="manual")
    staged = stages.stage_reviews(retry_run)
    deduplicated = read_json(stages.deduplicate_reviews(retry_run, staged))
    assert deduplicated["reviews"] == []
    assert deduplicated["duplicate_count"] == 2


def test_runtime_config_hash_rejects_changed_mapping_parameters(project_root):
    manifest = load_taxonomy_manifest(project_root / "config/taxonomy/2026-10-05_142933.json")
    config = load_normalization_config(project_root / "config/normalization/2026-10-05_142933.yaml")
    verify_normalization_config(config, manifest)
    changed = deepcopy(config)
    changed["clustering"]["experiment_d"]["aspect"]["distance_threshold"] += 0.01
    with pytest.raises(ValueError, match="normalization parameters differ"):
        verify_normalization_config(changed, manifest)


def test_reclustering_pipeline_uses_runtime_config_and_keeps_captured_source(runtime, monkeypatch):
    settings, sessions = runtime
    snapshot = settings.catalog_data_root / "input.duckdb"
    now = datetime.now(UTC)
    with duckdb.connect(str(snapshot)) as connection:
        connection.execute(SCHEMA_SQL)
        connection.execute("INSERT INTO products VALUES ('p', '상품', '모니터', 'input', ?)", [now])
        for index, (aspect, status) in enumerate([("화면", "밝음"), ("디스플레이", "어두움")]):
            connection.execute(
                "INSERT INTO reviews VALUES (?, 'test', ?, NULL, 'p', ?, ?, 'input', NULL, ?)",
                [f"r{index}", str(index), aspect, str(index) * 64, now],
            )
            connection.execute(
                "INSERT INTO opinion_units (opinion_unit_id, review_id, unit_position, raw_aspect, raw_status, "
                "excerpt, opinion, sentiment, mapping_state, prompt_version_id, model_version_id, "
                "mapping_table_version_id, embedding_model_version_id, normalization_run_id, "
                "normalization_config_sha256, extraction_response_sha256, ingestion_run_id, created_at) "
                "VALUES (?, ?, 1, ?, ?, ?, ?, 'positive', 'candidate', 'prompt', 'model', 'mapping', "
                "'embedding', 'run', ?, ?, 'input', ?)",
                [f"u{index}", f"r{index}", aspect, status, aspect, aspect, "c" * 64, "d" * 64, now],
            )
    source_sha = sha256_file(snapshot)
    monkeypatch.setattr(reclustering, "_current_snapshot", lambda: snapshot)

    class FakeEmbedder:
        def encode(self, texts):
            vectors = {
                "화면": [1.0, 0.0, 0.0],
                "디스플레이": [0.995, 0.1, 0.0],
                "밝음": [0.0, 1.0, 0.0],
                "어두움": [0.0, 0.995, 0.1],
            }
            array = np.asarray([vectors[text] for text in texts], dtype=np.float32)
            return array / np.linalg.norm(array, axis=1, keepdims=True)

    monkeypatch.setattr(reclustering, "build_embedder", lambda _settings: FakeEmbedder())
    run_id = reclustering.register_reclustering_run(
        dag_run_id="recluster-test",
        conf={},
        trigger_type="manual",
    )
    captured = reclustering.capture_catalog_snapshot(run_id)
    bundle_manifest = reclustering.build_full_reclustering(run_id, captured)
    pipeline_manifest = reclustering.commit_reclustering(run_id, bundle_manifest)
    result = read_json(pipeline_manifest)
    assert result["counts"]["captured_opinion_unit_count"] == 2
    assert sha256_file(snapshot) == source_sha
    with sessions() as session:
        run = session.get(PipelineRun, run_id)
        assert run.state == "pipeline_succeeded"
        assert len(run.conf_json["activate_component_versions"]) == 2
