"""Small public smoke set; not the independent final benchmark in the mission."""

import json
import statistics
import tempfile
import time
from pathlib import Path

from fastapi.testclient import TestClient

from maintain.app import create_app
from maintain.cli import seed
from maintain.config import Settings


def main():
    root = Path(__file__).resolve().parents[1]
    cases = [
        json.loads(line)
        for line in (root / "evaluations/smoke.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    outcomes = []
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "eval.sqlite"
        seed(database, root / "fixtures/synthetic")
        keys = json.loads((database.parent / "demo-credentials.json").read_text(encoding="utf-8"))
        with TestClient(create_app(Settings(database, requests_per_minute=1000))) as client:
            for case in cases:
                started = time.perf_counter()
                response = client.post(
                    "/v1/answers",
                    headers={
                        "Authorization": "Bearer " + keys["tech-a"],
                    },
                    json={"asset_id": case["asset_id"], "question": case["question"]},
                )
                milliseconds = (time.perf_counter() - started) * 1000
                result = response.json()
                passed = response.status_code == case.get("http", 200)
                if response.status_code == 200:
                    passed = passed and result["status"] == case["status"]
                    if "family" in case:
                        passed = passed and any(
                            all(s[k] == case[k] for k in ("family", "revision", "page"))
                            for s in result["sources"]
                        )
                    passed = passed and "B_PRIVATE" not in json.dumps(result)
                outcomes.append(
                    {"id": case["id"], "passed": passed, "latency_ms": round(milliseconds, 2)}
                )
    report = {
        "suite": "public_synthetic_smoke",
        "cases": len(outcomes),
        "passed": sum(o["passed"] for o in outcomes),
        "median_latency_ms": round(statistics.median(o["latency_ms"] for o in outcomes), 2),
        "limitations": "Tiny public fixture set; local TestClient, not a production benchmark.",
        "outcomes": outcomes,
    }
    output = root / "artifacts/evaluation.json"
    output.parent.mkdir(exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["passed"] == report["cases"] else 1)


if __name__ == "__main__":
    main()
