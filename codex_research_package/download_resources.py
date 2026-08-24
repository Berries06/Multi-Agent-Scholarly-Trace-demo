from __future__ import annotations

import csv
import hashlib
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE_CSV = ROOT / "resource_urls.csv"
OUT_DIR = ROOT / "resources"
MANIFEST = ROOT / "download_manifest.csv"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 Chrome/126 Safari/537.36 academic-resource-collector/1.0"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def valid_payload(data: bytes, kind: str) -> tuple[bool, str]:
    if kind == "pdf":
        if not data.startswith(b"%PDF-"):
            return False, "response is not a PDF"
        if len(data) < 10_000:
            return False, "PDF is unexpectedly small"
    elif kind == "html":
        head = data[:1000].lower()
        if b"<html" not in head and b"<!doctype" not in head:
            return False, "response is not HTML"
    return True, ""


def fetch(url: str, kind: str) -> tuple[bytes, str]:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/pdf,text/html,application/xhtml+xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as response:
        data = response.read()
        content_type = response.headers.get("Content-Type", "")
    ok, reason = valid_payload(data, kind)
    if not ok:
        raise ValueError(f"{reason}; content-type={content_type}")
    return data, content_type


def main() -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with SOURCE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    manifest_rows: list[dict[str, str | int]] = []
    for index, row in enumerate(rows, start=1):
        filename = row["filename"]
        target = OUT_DIR / filename
        status = "failed"
        detail = ""
        content_type = ""
        data = b""

        if target.exists():
            existing = target.read_bytes()
            ok, reason = valid_payload(existing, row["kind"])
            if ok:
                data = existing
                status = "existing"
            else:
                detail = f"invalid existing file: {reason}"

        if not data:
            for attempt in range(1, 4):
                try:
                    data, content_type = fetch(row["url"], row["kind"])
                    target.write_bytes(data)
                    status = "downloaded"
                    detail = ""
                    break
                except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
                    detail = f"attempt {attempt}: {type(exc).__name__}: {exc}"
                    if attempt < 3:
                        time.sleep(attempt * 2)

        manifest_rows.append(
            {
                "filename": filename,
                "status": status,
                "bytes": len(data),
                "sha256": sha256(data) if data else "",
                "content_type": content_type,
                "category": row["category"],
                "title": row["title"],
                "url": row["url"],
                "detail": detail,
            }
        )
        print(f"[{index:02d}/{len(rows):02d}] {status:10s} {filename}")

    fields = [
        "filename", "status", "bytes", "sha256", "content_type",
        "category", "title", "url", "detail",
    ]
    with MANIFEST.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(manifest_rows)

    succeeded = sum(r["status"] in {"downloaded", "existing"} for r in manifest_rows)
    print(f"Completed: {succeeded}/{len(manifest_rows)} valid resources")
    print(f"Manifest: {MANIFEST}")


if __name__ == "__main__":
    main()

