"""Regression tests for the machine-readable AI quality gate."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from pathlib import Path

from app.evaluation import quality
from app.evaluation.quality import evaluate_quality_dataset, load_quality_dataset


FIXTURE = Path(__file__).parent / "fixtures" / "ai_quality_baseline.json"
FIXED_NOW = datetime(2026, 7, 16, 8, 0, 0)


def _captured_predictions(report: dict, dataset_version: str) -> dict:
    classification = {
        case["id"]: case["actual"]
        for case in report["cases"]
        if case["kind"] == "classification"
    }
    generation = {
        case["id"]: {"summary": case["summary"]}
        for case in report["cases"]
        if case["kind"] == "generation"
    }
    return {
        "dataset_version": dataset_version,
        "classification": classification,
        "generation": generation,
    }


def test_fixed_baseline_passes_all_quality_gates() -> None:
    dataset = load_quality_dataset(FIXTURE)
    report = evaluate_quality_dataset(dataset, now=FIXED_NOW)

    assert report["passed"] is True
    assert report["errors"] == []
    assert all(metric["passed"] for metric in report["metrics"].values())
    assert report["metrics"]["classification_accuracy"]["value"] == 1.0
    assert report["metrics"]["ranking_pairwise_accuracy"]["value"] == 1.0
    assert report["metrics"]["citation_coverage"]["value"] == 1.0
    assert report["metrics"]["unsupported_claim_rate"]["value"] == 0.0


def test_captured_prediction_with_unsupported_number_fails_gate() -> None:
    dataset = load_quality_dataset(FIXTURE)
    baseline = evaluate_quality_dataset(dataset, now=FIXED_NOW)
    predictions = _captured_predictions(baseline, dataset["dataset"]["version"])
    predictions["generation"]["summary-multisource-agent-sdk"]["summary"] = (
        "OpenAI 发布 Agent SDK 2.0，并宣布获得 10 亿元融资。"
    )

    report = evaluate_quality_dataset(dataset, predictions=predictions, now=FIXED_NOW)

    assert report["passed"] is False
    metric = report["metrics"]["unsupported_claim_rate"]
    assert metric["value"] > metric["threshold"]
    case = next(item for item in report["cases"] if item["id"] == "summary-multisource-agent-sdk")
    assert "unsupported_number:10" in case["unsupported_claims"]


def test_missing_citation_is_visible_in_machine_report(monkeypatch) -> None:
    dataset = load_quality_dataset(FIXTURE)
    monkeypatch.setattr(quality, "generate_markdown", lambda *args, **kwargs: "# briefing without evidence")

    report = evaluate_quality_dataset(dataset, now=FIXED_NOW)

    assert report["passed"] is False
    assert report["metrics"]["citation_coverage"]["value"] == 0.0
    assert any(item["kind"] == "generation" and not item["passed"] for item in report["cases"])


def test_incomplete_prediction_snapshot_fails_closed() -> None:
    dataset = load_quality_dataset(FIXTURE)
    predictions = {
        "dataset_version": dataset["dataset"]["version"],
        "classification": {},
        "generation": {},
    }

    report = evaluate_quality_dataset(dataset, predictions=predictions, now=FIXED_NOW)

    assert report["passed"] is False
    assert any("missing cases" in error for error in report["errors"])
    assert report["metrics"]["summary_nonempty_rate"]["value"] == 0.0


def test_dataset_hash_changes_when_golden_expectation_changes() -> None:
    dataset = load_quality_dataset(FIXTURE)
    original = evaluate_quality_dataset(dataset, now=FIXED_NOW)
    changed_dataset = deepcopy(dataset)
    changed_dataset["classification_cases"][0]["expected_category"] = "综合"
    changed = evaluate_quality_dataset(changed_dataset, now=FIXED_NOW)

    assert original["dataset"]["sha256"] != changed["dataset"]["sha256"]
