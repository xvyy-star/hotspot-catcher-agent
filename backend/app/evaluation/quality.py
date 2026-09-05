"""Deterministic AI quality baseline for the hotspot analysis pipeline.

The production LLM is probabilistic and may be unavailable in CI. This module
therefore evaluates two stable surfaces:

1. The rules used when the LLM is unavailable (classification, ranking and
   fallback summaries).
2. Captured model predictions supplied as JSON, using the same golden inputs
   and quality gates without making a network request.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from copy import deepcopy
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from app.pipeline.analysis import classify_event, fallback_analysis
from app.pipeline.briefing import generate_markdown
from app.pipeline.scoring import score_events
from app.schemas import HotspotEventDTO


EVALUATOR_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = "1.0"
REQUIRED_THRESHOLDS = {
    "classification_accuracy": ">=",
    "ranking_pairwise_accuracy": ">=",
    "summary_fact_coverage": ">=",
    "citation_coverage": ">=",
    "summary_nonempty_rate": ">=",
    "unsupported_claim_rate": "<=",
}
_NUMBER_RE = re.compile(r"(?<![A-Za-z0-9])\d+(?:\.\d+)?%?")


def load_quality_dataset(path: str | Path) -> dict[str, Any]:
    """Load and validate a quality fixture."""
    dataset = json.loads(Path(path).read_text(encoding="utf-8"))
    _validate_dataset(dataset)
    return dataset


def load_predictions(path: str | Path) -> dict[str, Any]:
    """Load captured LLM predictions without contacting a model endpoint."""
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Predictions must be a JSON object")
    return value


def write_quality_report(report: dict[str, Any], path: str | Path) -> Path:
    """Persist a report atomically enough for local and CI usage."""
    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = output_path.with_suffix(output_path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary_path.replace(output_path)
    return output_path


def evaluate_quality_dataset(
    dataset: dict[str, Any],
    *,
    predictions: dict[str, Any] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Evaluate the current pipeline or a complete captured prediction set."""
    _validate_dataset(dataset)
    evaluation_now = now or datetime.utcnow()
    metadata = dataset["dataset"]
    dataset_version = str(metadata["version"])
    prediction_errors = _prediction_errors(dataset, predictions)

    classification_results, classification_correct = _evaluate_classification(
        dataset["classification_cases"], predictions, evaluation_now
    )
    ranking_results, ranking_correct, ranking_total = _evaluate_ranking(
        dataset["ranking_cases"], evaluation_now
    )
    generation_results, generation_totals = _evaluate_generation(
        dataset["generation_cases"],
        target_industry=str(metadata["target_industry"]),
        predictions=predictions,
        evaluation_now=evaluation_now,
        briefing_date=date.fromisoformat(str(metadata["as_of_date"])),
    )

    class_total = len(classification_results)
    generation_total = len(generation_results)
    metrics = {
        "classification_accuracy": _metric(
            classification_correct,
            class_total,
            dataset["thresholds"]["classification_accuracy"],
            ">=",
        ),
        "ranking_pairwise_accuracy": _metric(
            ranking_correct,
            ranking_total,
            dataset["thresholds"]["ranking_pairwise_accuracy"],
            ">=",
        ),
        "summary_fact_coverage": _metric(
            generation_totals["fact_hits"],
            generation_totals["fact_total"],
            dataset["thresholds"]["summary_fact_coverage"],
            ">=",
        ),
        "citation_coverage": _metric(
            generation_totals["citation_hits"],
            generation_totals["citation_total"],
            dataset["thresholds"]["citation_coverage"],
            ">=",
        ),
        "summary_nonempty_rate": _metric(
            generation_totals["nonempty_summaries"],
            generation_total,
            dataset["thresholds"]["summary_nonempty_rate"],
            ">=",
        ),
        "unsupported_claim_rate": _metric(
            generation_totals["unsupported_cases"],
            generation_total,
            dataset["thresholds"]["unsupported_claim_rate"],
            "<=",
        ),
    }
    passed = not prediction_errors and all(metric["passed"] for metric in metrics.values())
    cases = classification_results + ranking_results + generation_results
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluator_version": EVALUATOR_VERSION,
        "generated_at": evaluation_now.replace(microsecond=0).isoformat() + "Z",
        "mode": "captured_predictions" if predictions is not None else "offline_pipeline",
        "dataset": {
            "name": metadata["name"],
            "version": dataset_version,
            "sha256": _dataset_sha256(dataset),
        },
        "runtime": {"python": sys.version.split()[0]},
        "passed": passed,
        "errors": prediction_errors,
        "metrics": metrics,
        "failed_case_ids": [case["id"] for case in cases if not case["passed"]],
        "cases": cases,
    }


def _validate_dataset(dataset: dict[str, Any]) -> None:
    if not isinstance(dataset, dict):
        raise ValueError("Quality dataset must be a JSON object")
    metadata = dataset.get("dataset")
    if not isinstance(metadata, dict):
        raise ValueError("Quality dataset is missing dataset metadata")
    for key in ("name", "version", "target_industry", "as_of_date"):
        if not str(metadata.get(key) or "").strip():
            raise ValueError(f"Quality dataset metadata is missing {key}")
    try:
        date.fromisoformat(str(metadata["as_of_date"]))
    except ValueError as exc:
        raise ValueError("dataset.as_of_date must use YYYY-MM-DD") from exc

    thresholds = dataset.get("thresholds")
    if not isinstance(thresholds, dict):
        raise ValueError("Quality dataset is missing thresholds")
    for key in REQUIRED_THRESHOLDS:
        value = thresholds.get(key)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not 0 <= float(value) <= 1:
            raise ValueError(f"Threshold {key} must be between 0 and 1")

    for section in ("classification_cases", "ranking_cases", "generation_cases"):
        cases = dataset.get(section)
        if not isinstance(cases, list) or not cases:
            raise ValueError(f"Quality dataset requires non-empty {section}")
        ids = [str(case.get("id") or "") for case in cases if isinstance(case, dict)]
        if len(ids) != len(cases) or any(not case_id for case_id in ids) or len(ids) != len(set(ids)):
            raise ValueError(f"Every {section} case needs a unique id")


def _prediction_errors(dataset: dict[str, Any], predictions: dict[str, Any] | None) -> list[str]:
    if predictions is None:
        return []
    errors: list[str] = []
    expected_version = str(dataset["dataset"]["version"])
    if str(predictions.get("dataset_version") or "") != expected_version:
        errors.append(
            f"Prediction dataset_version must be {expected_version}; got {predictions.get('dataset_version')!r}"
        )
    for section, prediction_key in (
        ("classification_cases", "classification"),
        ("generation_cases", "generation"),
    ):
        values = predictions.get(prediction_key)
        if not isinstance(values, dict):
            errors.append(f"Predictions are missing object: {prediction_key}")
            values = {}
        missing = [case["id"] for case in dataset[section] if case["id"] not in values]
        if missing:
            errors.append(f"Predictions {prediction_key} missing cases: {', '.join(missing)}")
    return errors


def _event_from_fixture(payload: dict[str, Any], evaluation_now: datetime) -> HotspotEventDTO:
    event_data = deepcopy(payload)
    for item in event_data.get("items", []):
        age_hours = item.pop("captured_hours_ago", 0)
        if "captured_at" not in item:
            item["captured_at"] = evaluation_now - timedelta(hours=float(age_hours))
    return HotspotEventDTO.model_validate(event_data)


def _evaluate_classification(
    cases: list[dict[str, Any]],
    predictions: dict[str, Any] | None,
    evaluation_now: datetime,
) -> tuple[list[dict[str, Any]], int]:
    results: list[dict[str, Any]] = []
    correct = 0
    prediction_values = predictions.get("classification", {}) if predictions else {}
    for case in cases:
        event = _event_from_fixture(case["event"], evaluation_now)
        actual = prediction_values.get(case["id"], "") if predictions else classify_event(event)
        if isinstance(actual, dict):
            actual = actual.get("category", "")
        actual = str(actual or "").strip()
        expected = str(case["expected_category"])
        case_passed = actual == expected
        correct += int(case_passed)
        results.append(
            {
                "kind": "classification",
                "id": case["id"],
                "passed": case_passed,
                "expected": expected,
                "actual": actual,
                "source": "prediction" if predictions else "pipeline_rule",
            }
        )
    return results, correct


def _evaluate_ranking(
    cases: list[dict[str, Any]], evaluation_now: datetime
) -> tuple[list[dict[str, Any]], int, int]:
    results: list[dict[str, Any]] = []
    all_correct = 0
    all_pairs = 0
    for case in cases:
        events = [_event_from_fixture(item, evaluation_now) for item in case["events"]]
        ranked = score_events(events)
        actual_order = [event.event_key for event in ranked]
        expected_order = [str(value) for value in case["expected_order"]]
        positions = {event_key: index for index, event_key in enumerate(actual_order)}
        correct_pairs = 0
        total_pairs = 0
        for left_index, left in enumerate(expected_order):
            for right in expected_order[left_index + 1 :]:
                total_pairs += 1
                if left in positions and right in positions and positions[left] < positions[right]:
                    correct_pairs += 1
        all_correct += correct_pairs
        all_pairs += total_pairs
        results.append(
            {
                "kind": "ranking",
                "id": case["id"],
                "passed": correct_pairs == total_pairs and actual_order == expected_order,
                "expected_order": expected_order,
                "actual_order": actual_order,
                "correct_pairs": correct_pairs,
                "total_pairs": total_pairs,
                "scores": {event.event_key: event.heat_score for event in ranked},
            }
        )
    return results, all_correct, all_pairs


def _evaluate_generation(
    cases: list[dict[str, Any]],
    *,
    target_industry: str,
    predictions: dict[str, Any] | None,
    evaluation_now: datetime,
    briefing_date: date,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    results: list[dict[str, Any]] = []
    totals = {
        "fact_hits": 0,
        "fact_total": 0,
        "citation_hits": 0,
        "citation_total": 0,
        "nonempty_summaries": 0,
        "unsupported_cases": 0,
    }
    prediction_values = predictions.get("generation", {}) if predictions else {}
    for case in cases:
        event = fallback_analysis(_event_from_fixture(case["event"], evaluation_now), target_industry)
        if predictions is not None:
            prediction = prediction_values.get(case["id"], {})
            if isinstance(prediction, str):
                event.summary = prediction
            elif isinstance(prediction, dict):
                event.summary = str(prediction.get("summary") or "")
            else:
                event.summary = ""

        summary = " ".join(event.summary.split())
        required_facts = [str(value) for value in case.get("required_summary_facts", [])]
        fact_checks = [
            {"fact": fact, "found": _contains(summary, fact)}
            for fact in required_facts
        ]
        fact_hits = sum(int(check["found"]) for check in fact_checks)

        markdown = generate_markdown([event], briefing_date, {})
        citation_checks: list[dict[str, Any]] = []
        for url in case.get("required_evidence_urls", []):
            citation_checks.append(
                {"kind": "evidence_url", "target": str(url), "found": str(url) in markdown}
            )
        for reference in case.get("required_rag_references", []):
            marker = f"《{reference['document_title']}》chunk#{reference['chunk_index']}"
            citation_checks.append(
                {"kind": "rag_reference", "target": marker, "found": marker in markdown}
            )
        citation_hits = sum(int(check["found"]) for check in citation_checks)

        forbidden_hits = [
            str(claim)
            for claim in case.get("forbidden_summary_claims", [])
            if _contains(summary, str(claim))
        ]
        numeric_hits = _unsupported_numeric_claims(summary, event)
        unsupported_claims = forbidden_hits + [f"unsupported_number:{value}" for value in numeric_hits]
        has_unsupported = bool(unsupported_claims)
        nonempty = bool(summary)

        totals["fact_hits"] += fact_hits
        totals["fact_total"] += len(fact_checks)
        totals["citation_hits"] += citation_hits
        totals["citation_total"] += len(citation_checks)
        totals["nonempty_summaries"] += int(nonempty)
        totals["unsupported_cases"] += int(has_unsupported)

        results.append(
            {
                "kind": "generation",
                "id": case["id"],
                "passed": (
                    nonempty
                    and fact_hits == len(fact_checks)
                    and citation_hits == len(citation_checks)
                    and not has_unsupported
                ),
                "summary": summary,
                "summary_source": "prediction" if predictions else "pipeline_fallback",
                "fact_checks": fact_checks,
                "citation_checks": citation_checks,
                "unsupported_claims": unsupported_claims,
            }
        )
    return results, totals


def _contains(text: str, expected: str) -> bool:
    normalized_text = " ".join(text.split()).casefold()
    normalized_expected = " ".join(expected.split()).casefold()
    return bool(normalized_expected) and normalized_expected in normalized_text


def _canonical_numbers(text: str) -> set[str]:
    values: set[str] = set()
    for raw in _NUMBER_RE.findall(text or ""):
        try:
            value = Decimal(raw.rstrip("%")).normalize()
        except InvalidOperation:
            continue
        values.add(format(value, "f"))
    return values


def _unsupported_numeric_claims(summary: str, event: HotspotEventDTO) -> list[str]:
    source_parts = [event.title, str(event.source_count), str(event.heat_score), "100"]
    for item in event.items:
        source_parts.extend(
            [
                item.title,
                item.content or "",
                item.raw_hot_score or "",
                str(item.rank or ""),
                " ".join(item.tags),
            ]
        )
    for reference in event.rag_references:
        source_parts.extend(
            [
                str(reference.get("document_title") or ""),
                str(reference.get("preview") or ""),
                str(reference.get("chunk_index") or ""),
            ]
        )
    allowed = _canonical_numbers(" ".join(source_parts))
    return sorted(_canonical_numbers(summary) - allowed)


def _metric(numerator: int, denominator: int, threshold: float, operator: str) -> dict[str, Any]:
    value = round(numerator / denominator, 4) if denominator else 0.0
    threshold_value = float(threshold)
    passed = value >= threshold_value if operator == ">=" else value <= threshold_value
    return {
        "value": value,
        "threshold": threshold_value,
        "operator": operator,
        "passed": passed,
        "numerator": numerator,
        "denominator": denominator,
    }


def _dataset_sha256(dataset: dict[str, Any]) -> str:
    raw = json.dumps(dataset, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()
