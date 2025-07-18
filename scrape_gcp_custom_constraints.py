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

def _extract_resource_field(txt):
    txt = txt.strip('"')
    if not txt.startswith("resource."):
        return None
    # Fallback to previous split_ops logic for other operators (do this before regex, as it is faster)
    split_ops = [
        "=", "!", ">", "<", ">", "<", " "
    ]
    min_idx = None
    for op in split_ops:
        idx = txt.find(op)
        if idx != -1:
            if min_idx is None or idx < min_idx:
                min_idx = idx
    if min_idx is not None:
        field = txt[:min_idx].strip()
    else:
        # Generalise: find the first occurrence of a dot, then a word, then a (
        # e.g. resource.foo.contains(, resource.bar.startsWith(
        # If found, cut the field at the dot before the function call
        if '.' in txt and '(' in txt:
            match = re.search(r"\.[a-zA-Z]+\(", txt)
            if match:
                idx = match.start()
                field = txt[:idx].strip()
            else:
                field = txt.strip()
        else:
            field = txt.strip()
    if field.startswith("resource."):
        return field
    return None

def fetch_fields(doc_url):
    if not doc_url:
        return []
    try:
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

        # Also look for <span> with class starting with "devsite-syntax"
        for span in soup.find_all("span", class_=lambda c: c and c.startswith("devsite-syntax")):
            txt = span.get_text(strip=True)
            field = _extract_resource_field(txt)
            if field:
                fields.add(field)

        return sorted(fields)
    except Exception as e:
        print(f"Failed to fetch fields from {doc_url}: {e}")
        return []

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
