from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = PROJECT_ROOT / "data" / "vertical_kb" / "manifest.json"


def main() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    report = []
    for index, paper in enumerate(manifest["papers"]):
        destination = PROJECT_ROOT / paper["local_pdf"]
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists() and destination.stat().st_size > 10_000:
            status = "cached"
            content = destination.read_bytes()
        else:
            request = Request(
                paper["pdf_url"],
                headers={"User-Agent": "Yanhai-Scholarly-Trace/0.2"},
            )
            with urlopen(request, timeout=30) as response:  # noqa: S310 - manifest controlled
                content = response.read()
            if len(content) <= 10_000 or not content.startswith(b"%PDF"):
                raise RuntimeError(f"Invalid PDF payload: {paper['paper_id']}")
            destination.write_bytes(content)
            status = "downloaded"
            if index + 1 < len(manifest["papers"]):
                time.sleep(1)
        report.append(
            {
                "paper_id": paper["paper_id"],
                "path": str(destination.relative_to(PROJECT_ROOT)),
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "status": status,
                "source_url": paper["source_url"],
                "pdf_url": paper["pdf_url"],
            }
        )
        print(f"{status}: {paper['paper_id']} ({len(content)} bytes)")
    report_path = PROJECT_ROOT / "outputs" / "pdf-download-report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(
            {
                "domain": manifest["domain_name"],
                "version": manifest["version"],
                "files": report,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Wrote {report_path}")


if __name__ == "__main__":
    main()

