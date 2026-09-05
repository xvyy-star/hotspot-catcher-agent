"""Run the deterministic AI quality regression gate and emit JSON."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = PROJECT_ROOT / "backend"
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.evaluation.quality import (  # noqa: E402
    REPORT_SCHEMA_VERSION,
    evaluate_quality_dataset,
    load_predictions,
    load_quality_dataset,
    write_quality_report,
)


DEFAULT_DATASET = PROJECT_ROOT / "backend" / "tests" / "fixtures" / "ai_quality_baseline.json"
DEFAULT_OUTPUT = PROJECT_ROOT / "reports" / "ai_quality_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Evaluate hotspot AI quality gates without network access.")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET, help="Golden dataset JSON path")
    parser.add_argument("--predictions", type=Path, help="Complete captured model predictions JSON path")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Machine-readable report path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        dataset = load_quality_dataset(args.dataset)
        predictions = load_predictions(args.predictions) if args.predictions else None
        report = evaluate_quality_dataset(dataset, predictions=predictions)
    except Exception as exc:  # noqa: BLE001
        report = {
            "schema_version": REPORT_SCHEMA_VERSION,
            "generated_at": datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
            "passed": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
    write_quality_report(report, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report.get("passed") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
