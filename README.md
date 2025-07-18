# aws-guardduty-findings-directory
Regularly-updated directory of all finding types available in Amazon GuardDuty, sourced from AWS documentation

## Automation

This repository includes a GitHub Actions workflow that scrapes the AWS GuardDuty documentation for the list of active finding types. The workflow runs weekly and updates [`findings.json`](findings.json) with the latest information.

To execute the scraper locally:

```bash
pip install -r requirements.txt
python scrape_guardduty_findings.py
```

The output JSON has the following structure:

```json
{
  "findings": [
    {
      "type": "Finding type string",
      "resource_type": "Resource",
      "source": "Source",
      "severity": "Severity",
      "services": ["ecs", "eks"]
    }
  ]
}
```

If a finding's type, resource type or source doesn't map to any AWS service, the scraper exits with an error so the workflow fails.
