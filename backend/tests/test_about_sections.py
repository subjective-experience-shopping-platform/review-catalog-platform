from __future__ import annotations

from importlib.resources import files

import httpx
import pytest
from fastapi import HTTPException

from review_catalog.api import routes
from review_catalog.settings import Settings


class _ReadmeResponse:
    text = "# remote README\n"

    def raise_for_status(self) -> None:
        return None


def test_about_sections_explain_remote_readme_failures(monkeypatch) -> None:
    def fake_get(*_args, **_kwargs):
        raise httpx.ConnectError("GitHub unavailable")

    monkeypatch.setattr(routes.httpx, "get", fake_get)
    with pytest.raises(HTTPException) as exc_info:
        routes.about_section("overview", Settings())
    assert exc_info.value.status_code == 503
    assert exc_info.value.detail == routes.README_UNAVAILABLE_MESSAGE


@pytest.mark.parametrize("section", ["overview", "release"])
def test_current_chapters_fetch_their_source(section, monkeypatch) -> None:
    calls = []

    def fake_get(url, **kwargs):
        calls.append((url, kwargs))
        return _ReadmeResponse()

    monkeypatch.setattr(routes.httpx, "get", fake_get)
    result = routes.about_section(section, Settings(readme_request_timeout_seconds=2.5))
    assert result == {
        "markdown": "# remote README\n",
        "source_url": routes.REMOTE_README_URLS[section],
    }
    assert calls == [
        (routes.REMOTE_README_URLS[section], {"follow_redirects": True, "timeout": 2.5})
    ]


@pytest.mark.parametrize("section", ["about-me", "unknown"])
def test_removed_and_unknown_chapters_are_not_served(section) -> None:
    with pytest.raises(HTTPException) as exc_info:
        routes.about_section(section, Settings())
    assert exc_info.value.status_code == 404


def test_experiment_document_is_served_from_backend_package(monkeypatch):
    monkeypatch.delenv("REVIEW_CATALOG_EXPERIMENT_MARKDOWN_PATH", raising=False)
    settings = Settings(_env_file=None)
    result = routes.about_section("experiment", settings)
    assert result["source_url"] is None
    assert result["markdown"] == files("review_catalog").joinpath(
        "content/experiment.md"
    ).read_text(encoding="utf-8")


def test_missing_experiment_document_returns_unavailable(tmp_path):
    with pytest.raises(HTTPException) as exc_info:
        routes.about_section(
            "experiment", Settings(experiment_markdown_path=tmp_path / "missing.md")
        )
    assert exc_info.value.status_code == 503
