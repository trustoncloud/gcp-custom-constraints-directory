import requests
from bs4 import BeautifulSoup
import json
import re
import time

BASE_URL = "https://cloud.google.com"
MAIN_URL = "https://cloud.google.com/resource-manager/docs/organization-policy/custom-constraint-supported-services"

def fetch_main_table():
    resp = requests.get(MAIN_URL)
    resp.raise_for_status()
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

OVERWRITE_URL = {
    'https://cloud.google.com/service-mesh/docs/custom-constraints': 'https://cloud.google.com/service-mesh/v1.25/docs/service-routing/custom-constraints'
}

@lru_cache(maxsize=300)
def fetch_fields(doc_url) -> list | dict[list]:
    if not doc_url:
        return []
    try:
        if doc_url in OVERWRITE_URL:
            doc_url = OVERWRITE_URL[doc_url]
        resp = requests.get(doc_url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        # Helper: parse a table and return a dict of resource_type -> set(fields)
        def parse_resource_field_table(table):
            header_cells = [th.get_text(strip=True).lower() for th in table.find_all("th")]
            resource_idx = None
            field_indices = []
            for i, h in enumerate(header_cells):
                if "resource" in h:
                    resource_idx = i
                if "field" in h:
                    field_indices.append(i)
            resource_fields = {}
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                if not cells or all(not c.get_text(strip=True) for c in cells):
                    continue
                # If both resource and field columns
                if resource_idx is not None and field_indices:
                    if len(cells) > max(resource_idx, max(field_indices)):
                        resource_val = cells[resource_idx].get_text(strip=True)
                        for idx in field_indices:
                            val = cells[idx].get_text(strip=True)
                            if val and "field" not in val.lower():
                                if not val.startswith("resource."):
                                    val = "resource." + val
                                resource_fields.setdefault(resource_val, set()).add(val)
                # If only field columns (single resource type for this doc)
                elif resource_idx is None and field_indices:
                    for idx in field_indices:
                        if len(cells) > idx:
                            val = cells[idx].get_text(strip=True)
                            if val and "field" not in val.lower():
                                if not val.startswith("resource."):
                                    val = "resource." + val
                                resource_fields.setdefault(None, set()).add(val)
            return resource_fields

        # Special handling for Dataflow and Filestore custom constraints docs and similar
        if (
            doc_url.startswith("https://cloud.google.com/dataflow/docs/custom-constraints")
            or doc_url.startswith("https://cloud.google.com/filestore/docs/create-custom-constraints")
        ):
            # Find the first table with a header containing "field"
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
                    # For Filestore, the doc lists resource types in a bullet list above the table
                    # We'll try to find the first code block with file.googleapis.com/...
                    resource_type = None
                    code = soup.find("code", string=re.compile(r"file\.googleapis\.com/"))
                    if code:
                        resource_type = code.get_text(strip=True)
                    # Fallback: if only one resource_type in constraints.json for this doc_url, use that
                    if not resource_type:
                        # This is a fallback for the main script, not for fetch_fields, so just return the fields
                        return sorted(resource_fields[None])
                    return {resource_type: sorted(resource_fields[None])}
                else:
                    # Return dict of resource_type -> sorted fields
                    return {k: sorted(v) for k, v in resource_fields.items() if k}
            else:
                return []

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
    for c in constraints:
        if c["doc_url"]:
            time.sleep(0.5)  # Be polite to GCP docs
            c["fields"] = fetch_fields(c["doc_url"])
        else:
            c["fields"] = []
    out = {"constraints": constraints}
    with open("custom_constraints.json", "w", encoding="utf-8") as f:
        json.dump(out, f, indent=2, ensure_ascii=False)
    print("Wrote custom_constraints.json")

if __name__ == "__main__":
    main()
