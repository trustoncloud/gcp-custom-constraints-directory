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
        if len(cols) < 3:
            continue
        # Service name is only in the first col of a new group
        service = cols[0].get_text(strip=True) or current_service
        if service:
            current_service = service
        resource_type_html = cols[1]
        launch_status = cols[2].get_text(strip=True)
        # Find resource type and doc link
        code = resource_type_html.find("code")
        if not code:
            continue
        resource_type = code.get_text(strip=True)
        a = resource_type_html.find("a")
        doc_url = BASE_URL + a["href"] if a and a["href"].startswith("/") else a["href"] if a else None
        constraints.append({
            "service": current_service,
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

OVERWRITE_URL = {
    'https://cloud.google.com/service-mesh/docs/custom-constraints': 'https://cloud.google.com/service-mesh/v1.25/docs/service-routing/custom-constraints'
}

def fetch_fields(doc_url):
    if not doc_url:
        return []
    try:
        if doc_url in OVERWRITE_URL:
            doc_url = OVERWRITE_URL[doc_url]
        resp = requests.get(doc_url)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        fields = set()

        # Find all <code> tags with text starting with 'resource.'
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
