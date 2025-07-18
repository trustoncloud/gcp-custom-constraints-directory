# gcp-custom-constraints-directory

Regularly-updated directory of all custom constraint resource types and fields available in Google Cloud Platform (GCP) Organisation Policy, sourced from GCP documentation.

## Automation

This repository includes a GitHub Actions workflow that scrapes the GCP documentation for the list of supported custom constraint resource types and their fields. The workflow runs daily and updates [`custom_constraints.json`](custom_constraints.json) with the latest information.

To execute the scraper locally:

```bash
pip install -r requirements.txt
python scrape_gcp_custom_constraints.py
```

The output JSON has the following structure:

```json
{
  "constraints": [
    {
      "service": "Service name",
      "resource_type": "Resource type string",
      "launch_status": "GA/Preview/...",
      "doc_url": "Documentation URL",
      "fields": [
        "resource.field1",
        "resource.field2",
        ...
      ]
    }
  ]
}
```

Each entry describes a GCP resource type that supports custom constraints, including the service, resource type, launch status, documentation link, and a list of available fields for use in custom constraints.

If the scraper cannot map a resource type or field as expected, it will exit with an error so the workflow fails.
