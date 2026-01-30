import requests
from bs4 import BeautifulSoup
import json
import re
import time
import random
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_URL = "https://docs.cloud.google.com"
MAIN_URL = "https://docs.cloud.google.com/resource-manager/docs/organization-policy/custom-constraint-supported-services"

OVERWRITE_URL = {
    'https://docs.cloud.google.com/resource-manager/docs/organization-policy/certificate-authority-service/docs/custom-constraints': 'https://docs.cloud.google.com/certificate-authority-service/docs/custom-constraints',
    'https://docs.cloud.google.com/vertex-ai/docs/prediction/custom-constraints': 'https://docs.cloud.google.com/vertex-ai/docs/predictions/custom-constraints',
    'https://docs.cloud.google.com/backup-disaster-recovery/docs/custom-constraints': 'https://docs.cloud.google.com/backup-disaster-recovery/docs/customconstraints'
}
URLS_WITH_TEMPORARY_ISSUES = {
    'https://docs.cloud.google.com/resource-manager/docs/organization-policy/artifact-analysis/docs/custom-constraints': datetime(2026, 2, 28, tzinfo=timezone.utc)
}
'''
Usage of URLS_WITH_TEMPORARY_ISSUES. Add the URL and the date when the error should resurface
{
    'https://docs.cloud.google.com/dataform/docs/create-custom-constraints': datetime(2025, 11, 3, tzinfo=timezone.utc)
}
'''

MAX_HTTP_RETRIES = 5
MAX_BACKOFF_SECONDS = 300  # 5 minutes
REQUEST_TIMEOUT_SECONDS = 30



def _http_get_with_retry(url: str, *, timeout_seconds: int = REQUEST_TIMEOUT_SECONDS) -> requests.Response:
    start_time = time.monotonic()
    last_exc: Exception | None = None

    for attempt in range(MAX_HTTP_RETRIES):
        try:
            resp = requests.get(url, timeout=timeout_seconds)
            resp.raise_for_status()
            return resp
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_exc = exc
        except requests.exceptions.HTTPError as exc:
            last_exc = exc
            status_code: Any = getattr(getattr(exc, "response", None), "status_code", None)
            if status_code not in (429, 500, 502, 503, 504):
                raise

        if attempt == MAX_HTTP_RETRIES - 1:
            raise

        elapsed = time.monotonic() - start_time
        if elapsed >= MAX_BACKOFF_SECONDS:
            raise

        backoff = min(2 ** attempt, MAX_BACKOFF_SECONDS)
        jitter_factor = random.uniform(0.5, 1.5)
        sleep_seconds = backoff * jitter_factor

        remaining_window = MAX_BACKOFF_SECONDS - elapsed
        if remaining_window <= 0:
            raise

        sleep_seconds = min(sleep_seconds, remaining_window)
        time.sleep(sleep_seconds)

    if last_exc is not None:
        raise last_exc
    raise RuntimeError(f"HTTP GET failed without exception for url={url!r}")


def fetch_main_table():
    resp = _http_get_with_retry(MAIN_URL)
    soup = BeautifulSoup(resp.text, "html.parser")
    # Find the table after the "Supported service resources" heading
    heading = soup.find(id="supported_service_resources")
    table = None
    for sib in heading.find_all_next():
        if sib.name == "table":
            table = sib
            break
    if not table:
        raise Exception("Could not find supported service resources table")
    return table

def parse_table(table):
    constraints = []
    current_service = None
    for row in table.find_all("tr"):
        cols = row.find_all(["td", "th"])
        if len(cols) == 3:
            # Service name is only in the first col of a new group
            service = cols[0].get_text(strip=True) or current_service
            index_shift = 0
            if service:
                current_service = service
        elif len(cols) == 2:
            service = current_service
            index_shift = 1
        else:
            continue
        resource_type_html = cols[1 - index_shift]
        launch_status = cols[2 - index_shift].get_text(strip=True)
        # Find resource type and doc link
        code = resource_type_html.find("code")
        if not code:
            continue
        resource_type = code.get_text(strip=True)
        a = resource_type_html.find("a")
        doc_url = BASE_URL + a["href"] if a and a["href"].startswith("/") else a["href"] if a else None
        constraints.append({
            "service": current_service,
            "namespace": resource_type.split('.')[0],
            "resource_type": resource_type,
            "launch_status": launch_status,
            "doc_url": doc_url,
        })
    return constraints

OPERATIONS_TO_REMOVE = ['.matches(', '.startsWith(', '.endsWith(', '.contains(']
def _extract_resource_field(txt):
    txt = txt.strip('"')
    for operation in OPERATIONS_TO_REMOVE:
        txt = txt.replace(operation, ' ')
    if not txt.startswith("resource."):
        return None
    # Fallback to previous split_ops logic for other operators (do this before regex, as it is faster)
    split_ops = [
        "=", "!", ">", "<", ">", "<", " "
    ]
    for op in split_ops:
        if op in txt:
            txt = txt.split(op)[0]
    field = txt.strip()
    if '(' in field:
        return None
    if field.startswith("resource."):
        return field
    return None

from functools import lru_cache

@lru_cache(maxsize=300)
def fetch_fields(doc_url) -> list | dict[list]:
    if not doc_url:
        return []
    try:
        if doc_url in OVERWRITE_URL.keys():
            print(f'Overwrite {doc_url} to {OVERWRITE_URL[doc_url]}')
            doc_url = OVERWRITE_URL[doc_url]
        resp = _http_get_with_retry(doc_url)
        soup = BeautifulSoup(resp.text, "html.parser")

        # Helper: parse a table and return a dict of resource_type -> set(fields)
        def parse_resource_field_table(table):
            header_cells = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            resource_idx = None
            field_idx = None
            for i, h in enumerate(header_cells):
                if "resource" in h:
                    resource_idx = i
                if "field" in h:
                    field_idx = i
            if resource_idx and resource_idx != 0:
                raise ValueError(f"Different table for resource types in {doc_url}")
            if field_idx and field_idx != 1:
                raise ValueError(f"Different table for fields in {doc_url}")
            resource_fields = {}
            current_resource = None
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells or all(not c.get_text(strip=True) for c in cells):
                    continue
                # If both resource and field columns
                if resource_idx is not None and field_idx is not None:
                    if len(cells) == 2:
                        resource_val = cells[resource_idx].get_text(strip=True)
                        current_resource = resource_val
                        val = cells[field_idx].get_text(strip=True)
                    elif len(cells) == 1:
                        resource_val = current_resource
                        val = cells[field_idx-1].get_text(strip=True)
                    if val and "field" not in val.lower():
                        if not val.startswith("resource."):
                            val = "resource." + val
                        resource_fields.setdefault(resource_val, set()).add(val)
                # If only field columns (single resource type for this doc)
                elif resource_idx is None and field_idx is not None:
                    val = cells[field_idx].get_text(strip=True)
                    if val and "field" not in val.lower():
                        if not val.startswith("resource."):
                            val = "resource." + val
                        resource_fields.setdefault(None, set()).add(val)
            return resource_fields

        # Generalised: If there is a table with a "field" header, extract fields as per table structure
        table = None
        for t in soup.find_all("table"):
            headers = [th.get_text(strip=True).lower() for th in t.find_all("th")]
            if any("field" in h for h in headers):
                table = t
                break
        if table:
            resource_fields = parse_resource_field_table(table)
            # If only one resource_type in this doc, attach all fields to it
            if None in resource_fields:
                # Try to infer the resource_type from the doc context
                resource_type = None
                code = soup.find("code", string=re.compile(r"\w+\.googleapis\.com/"))
                if code:
                    resource_type = code.get_text(strip=True)
                if not resource_type:
                    return sorted(resource_fields[None])
                return {resource_type: sorted(resource_fields[None])}
            else:
                return {k: sorted(v) for k, v in resource_fields.items() if k}

        # Find all <code> tags with text starting with 'resource.'
        fields = set()
        for code in soup.find_all("code"):
            txt = code.get_text(strip=True)
            field = _extract_resource_field(txt)
            if field:
                fields.add(field)

        return sorted(fields)

    except Exception as e:
        print(f"Failed to fetch fields from {doc_url}: {e}")
        raise

def main():
    print("Fetching main table...")
    table = fetch_main_table()
    print("Parsing table...")
    constraints = parse_table(table)
    print(f"Found {len(constraints)} resource types. Fetching fields...")

    # Count how many times each doc_url appears in constraints
    url_count = {}
    for c in constraints:
        if c["doc_url"]:
            url_count[c["doc_url"]] = url_count.get(c["doc_url"], 0) + 1

    for c in constraints:
        if c["doc_url"]:
            time.sleep(0.5)  # Be polite to GCP docs
            # Attempt to fetch fields; if this specific doc returns a 404, skip it (temporary bypass until 2025-11-03)
            try:
                fields = fetch_fields(c["doc_url"])
            except requests.exceptions.HTTPError as http_err:
                if (c['doc_url'] in URLS_WITH_TEMPORARY_ISSUES
                        and getattr(http_err.response, "status_code", None) == 404
                        and datetime.now(timezone.utc) < URLS_WITH_TEMPORARY_ISSUES[c['doc_url']]
                    ):
                    continue
                raise
            if isinstance(fields, list) and url_count[c["doc_url"]] == 1:
                c["fields"] = fields
            elif isinstance(fields, dict):
                c["fields"] = fields.get(c['resource_type'], [])
            else:
                c["fields"] = []
        else:
            c["fields"] = []
    out = {"constraints": constraints}
    try:
        repo_root = Path(__file__).resolve().parents[2]
        out_path = repo_root / "custom_constraints.json"
    except Exception:
        out_path = Path.cwd() / "custom_constraints.json"
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"Wrote {out_path}")
    except OSError:
        fallback_path = Path.cwd() / "custom_constraints.json"
        with fallback_path.open("w", encoding="utf-8") as f:
            json.dump(out, f, indent=2, ensure_ascii=False)
        print(f"Wrote {fallback_path}")

if __name__ == "__main__":
    main()
