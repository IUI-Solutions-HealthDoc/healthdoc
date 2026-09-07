#!/usr/bin/env python3
"""Read-only Postman inventory. Never execute collection scripts or emit values.

Checks configured outbound paths, not certification or full payload compliance.
Environment files and response examples can contain credentials/PII: they are
deliberately not printed or needed by this check.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]


def requests(items):
    for item in items:
        yield from requests(item.get("item", []))
        if isinstance(item.get("request"), dict):
            yield item["request"]


def request_path(request):
    url = request.get("url", "")
    raw = url.get("raw", "") if isinstance(url, dict) else url
    raw = raw.split("?")[0]
    if raw.startswith("{{abha_url}}"):
        return "/v3/" + raw.removeprefix("{{abha_url}}").lstrip("/")
    if raw.startswith("{{"):
        return "/" + re.sub(r"^\{\{[^}]+\}\}", "", raw).lstrip("/")
    path = urlsplit(raw).path
    return path.removeprefix("/abha/api") if path.startswith("/abha/api/") else path


def audit(collection_dir: Path, config: Path):
    files, paths, production_requests, legacy_sessions = [], set(), 0, 0
    for file in sorted(collection_dir.glob("*collection*.json")):
        raw = file.read_bytes()
        collection = json.loads(raw)
        entries = list(requests(collection.get("item", [])))
        files.append({"file": file.name, "sha256": hashlib.sha256(raw).hexdigest(), "requests": len(entries)})
        for request in entries:
            path = request_path(request)
            paths.add(path)
            url = request.get("url", "")
            raw_url = url.get("raw", "") if isinstance(url, dict) else url
            production_requests += urlsplit(raw_url).hostname in {"abha.abdm.gov.in", "live.abdm.gov.in"}
            legacy_sessions += bool(re.search(r"/(?:v0\.5|v1)/sessions$", path))
    settings = {}
    for node in ast.walk(ast.parse(config.read_text())):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            if name.startswith("abdm_path_") or name == "abdm_session_path":
                if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                    settings[name] = {"path": node.value.value, "in_supplied_collection": node.value.value in paths}
    return {"collections": files, "requests": sum(f["requests"] for f in files),
            "production_host_requests": production_requests, "legacy_session_requests": legacy_sessions,
            "outbound_path_checks": settings,
            "limits": "Path presence only; no request execution, credentials, payload values or certification verdict."}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collections", type=Path, default=ROOT / "Postman collections from ABDM")
    args = parser.parse_args()
    if not args.collections.is_dir():
        parser.error("Collection directory is missing")
    report = audit(args.collections, ROOT / "backend/app/common/config.py")
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["collections"] and all(x["in_supplied_collection"] for x in report["outbound_path_checks"].values()) else 1)
