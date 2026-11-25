"""Smoke-test the packaged Windows executable with synthetic files and temp-file monitoring."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

import httpx


def build_synthetic_pdf(page_texts: list[str]) -> bytes:
    """Create a minimal valid PDF 1.4 document with one text stream per page."""
    objects: list[bytes] = [b"", b""]
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    font_id = 3
    page_ids: list[int] = []

    for text in page_texts:
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET\n".encode("latin-1") if escaped else b""
        content_body = (
            f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream"
        )
        objects.append(content_body)
        content_id = len(objects)
        page_body = (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
            f"/Resources << /Font << /F1 {font_id} 0 R >> >> "
            f"/Contents {content_id} 0 R >>"
        ).encode("ascii")
        objects.append(page_body)
        page_ids.append(len(objects))

    kids = " ".join(f"{pid} 0 R" for pid in page_ids)
    objects[0] = b"<< /Type /Catalog /Pages 2 0 R >>"
    objects[1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_ids)} >>".encode("ascii")

    out = bytearray(b"%PDF-1.4\n")
    offsets: list[int] = [0]
    for obj_num, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out.extend(f"{obj_num} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    xref_pos = len(out)
    out.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))

    out.extend(
        (
            f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_pos}\n%%EOF\n"
        ).encode("ascii")
    )
    return bytes(out)


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_health(
    base_url: str,
    proc: subprocess.Popen[str],
    timeout: float = 20.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=2)
            raise RuntimeError(
                f"Packaged app exited early with code {proc.returncode}.\n"
                f"STDOUT:\n{stdout}\nSTDERR:\n{stderr}"
            )
        try:
            response = httpx.get(f"{base_url}/health", timeout=1.0)
            if response.status_code == 200 and response.json().get("status") == "ok":
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"Packaged app did not become healthy at {base_url} within {timeout}s.")


def run_smoke_test(exe_path: Path) -> None:
    if not exe_path.is_file():
        raise FileNotFoundError(f"Executable not found: {exe_path}")

    port = find_free_port()
    base_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix="din_smoke_tmp_") as isolated_tmp_str:
        isolated_tmp = Path(isolated_tmp_str)
        observed_temp_entries: set[str] = set()
        stop_watcher = threading.Event()

        def watch_temp_dir() -> None:
            while not stop_watcher.is_set():
                try:
                    for entry in isolated_tmp.rglob("*"):
                        observed_temp_entries.add(str(entry.relative_to(isolated_tmp)))
                except OSError:
                    pass
                time.sleep(0.01)

        watcher = threading.Thread(target=watch_temp_dir, daemon=True)
        watcher.start()

        env = os.environ.copy()
        env["TEMP"] = str(isolated_tmp)
        env["TMP"] = str(isolated_tmp)
        env.pop("AZURE_DOCUMENT_INTELLIGENCE_ENDPOINT", None)
        env.pop("AZURE_DOCUMENT_INTELLIGENCE_KEY", None)

        proc = subprocess.Popen(
            [str(exe_path), "--host", "127.0.0.1", "--port", str(port), "--no-browser"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

        try:
            wait_for_health(base_url, proc)

            with httpx.Client(base_url=base_url, timeout=20.0) as client:
                ui_resp = client.get("/search")
                assert ui_resp.status_code == 200
                assert "Open PDF / JSON files" in ui_resp.text

                # > 1 MB synthetic PDF and JSON to cross Starlette's 1 MB default spool threshold
                filler = (
                    "Synthetic ISMS baseline padding text for >1MB offline upload verification. "
                    * 3800
                )
                pdf_bytes = build_synthetic_pdf(
                    [
                        f"Synthetic ISMS Cover {filler}",
                        f"Page Two Governance {filler}",
                        f"Page Three Risk Scope {filler}",
                        f"Page Four Asset Register {filler}",
                        "Page Five: Quarterly backup restoration drill verified.",
                        f"Page Six Appendix {filler}",
                    ]
                )
                json_bytes = json.dumps(
                    {
                        "assessment": {
                            "padding": "P" * 1_250_000,
                            "controls": [
                                {"id": "CTRL-01", "evidence": {"owner": "Platform"}},
                                {
                                    "id": "CTRL-02",
                                    "evidence": {
                                        "owner": "SecOps",
                                        "notes": "Pending quarterly tabletop validation.",
                                    },
                                },
                            ],
                        }
                    }
                ).encode("utf-8")

                assert len(pdf_bytes) > 1_048_576, "Synthetic PDF must exceed 1 MB"
                assert len(json_bytes) > 1_048_576, "Synthetic JSON must exceed 1 MB"

                upload = client.post(
                    "/api/v1/session/files",
                    files=[
                        ("files", ("synthetic-isms-policy.pdf", pdf_bytes, "application/pdf")),
                        ("files", ("synthetic-isms-controls.json", json_bytes, "application/json")),
                    ],
                )
                assert upload.status_code == 200, upload.text
                assert upload.json()["session"]["document_count"] == 2

                pdf_search = client.get(
                    "/api/v1/search",
                    params={"q": "Quarterly backup restoration drill", "scope": "session"},
                )
                assert pdf_search.status_code == 200
                pdf_hits = pdf_search.json()["results"]
                assert len(pdf_hits) == 1
                assert pdf_hits[0]["page_number"] == 5

                pdf_stream = client.get(
                    f"/api/v1/session/documents/{pdf_hits[0]['document_id']}/pdf"
                )
                assert pdf_stream.status_code == 200
                assert pdf_stream.content.startswith(b"%PDF-1.4")

                json_search = client.get(
                    "/api/v1/search",
                    params={"q": "tabletop validation", "scope": "session"},
                )
                assert json_search.status_code == 200
                json_hits = json_search.json()["results"]
                assert len(json_hits) == 1
                assert json_hits[0]["field_path"] == "/assessment/controls/1/evidence/notes"

                clear = client.post("/api/v1/session/clear")
                assert clear.status_code == 200
                assert clear.json()["document_count"] == 0

                after_pdf = client.get(
                    "/api/v1/search",
                    params={"q": "Quarterly backup restoration drill", "scope": "session"},
                )
                after_json = client.get(
                    "/api/v1/search",
                    params={"q": "tabletop validation", "scope": "session"},
                )
                assert after_pdf.json()["count"] == 0
                assert after_json.json()["count"] == 0
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            stop_watcher.set()
            watcher.join(timeout=2)

        remaining_after_exit = [
            str(entry.relative_to(isolated_tmp)) for entry in isolated_tmp.rglob("*")
        ]
        assert not observed_temp_entries, (
            f"Temporary files were created during import/run: {sorted(observed_temp_entries)}"
        )
        assert not remaining_after_exit, (
            f"Temporary files remained after exit: {sorted(remaining_after_exit)}"
        )

    print(
        f"SMOKE TEST PASSED: health, /search UI, >1MB PDF ({len(pdf_bytes)} B) page-5 hit, "
        f"PDF stream, >1MB JSON ({len(json_bytes)} B) nested field hit, clear, "
        "0 temp files observed during import/clear/exit."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke-test built Windows executable.")
    parser.add_argument(
        "exe_path",
        nargs="?",
        default="dist/DocumentIntelligenceNavigator/DocumentIntelligenceNavigator.exe",
        help="Path to the built Windows executable.",
    )
    args = parser.parse_args()
    run_smoke_test(Path(args.exe_path))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"SMOKE TEST FAILED: {exc}", file=sys.stderr)
        raise
