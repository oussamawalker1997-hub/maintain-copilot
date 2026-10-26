"""Exercise a real loopback server; never use the developer's own database or keys."""

import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from maintain.cli import seed


def main():
    root = Path(__file__).resolve().parents[1]
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "live.sqlite"
        seed(database, root / "fixtures/synthetic")
        keys = json.loads((database.parent / "demo-credentials.json").read_text(encoding="utf-8"))
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = listener.getsockname()[1]
        env = os.environ | {"PYTHONPATH": str(root / "src")}
        server = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "maintain.cli",
                "--database",
                str(database),
                "serve",
                "--port",
                str(port),
            ],
            cwd=root,
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        def call(path, data=None, extra=None):
            request = urllib.request.Request(
                f"http://127.0.0.1:{port}" + path,
                data=json.dumps(data).encode() if data is not None else None,
                headers={
                    "Authorization": "Bearer " + keys["tech-a"],
                    "Content-Type": "application/json",
                }
                | (extra or {}),
            )
            with urllib.request.urlopen(request, timeout=3) as response:
                return response.headers, response.read()

        try:
            for _ in range(100):
                if server.poll() is not None:
                    raise RuntimeError("Local server exited during startup")
                try:
                    call("/healthz")
                    break
                except (urllib.error.URLError, TimeoutError):
                    time.sleep(0.05)
            else:
                raise RuntimeError("Local server startup timed out")
            response_headers, html = call("/")
            assert b"MAINTAIN" in html
            assert "X-Trace-ID" in response_headers
            _, docs = call("/docs")
            assert b"/openapi.json" in docs
            _, schema = call("/openapi.json")
            assert "/v1/answers" in json.loads(schema)["paths"]
            _, raw = call("/v1/answers", {"asset_id": "NW-P17", "question": "E042"})
            result = json.loads(raw)
            assert result["status"] == "evidence_found"
            source = result["sources"][0]
            call(f"/v1/documents/{source['document_id']}/pages/{source['page']}")
            _, raw_ticket = call(
                "/v1/tickets",
                {
                    "run_id": result["run_id"],
                    "asset_id": "NW-P17",
                    "observations": "Live synthetic test",
                    "confirmed": True,
                },
                {"Idempotency-Key": "live-smoke-confirmed-ticket"},
            )
            ticket = json.loads(raw_ticket)
            subprocess.run(
                [sys.executable, "-m", "maintain.cli", "--database", str(database), "dispatch"],
                cwd=root,
                env=env,
                check=True,
                capture_output=True,
            )
            _, delivered = call(f"/v1/tickets/{ticket['id']}")
            assert json.loads(delivered)["status"] == "sent"
            print("PASS: live HTTP, UI files, OpenAPI, scoped evidence, confirmed ticket, dispatch")
        finally:
            server.terminate()
            try:
                server.wait(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait(timeout=5)


if __name__ == "__main__":
    main()
