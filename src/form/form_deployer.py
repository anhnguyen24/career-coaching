"""
form/form_deployer.py — Updates Google Form question descriptions

What it does:
- Reads all 180 questions from survey JSON
- Updates each question's description (help text) in the Google Form
- Titles (Câu 1...Câu 180) are never touched — they're the stable keys
- Reports which questions changed vs stayed the same
"""

import os
import time
from google.oauth2 import service_account
from googleapiclient.discovery import build


SCOPES = ["https://www.googleapis.com/auth/forms.body"]


class FormDeployer:

    def __init__(self, survey: dict):
        self._survey  = survey
        self._form_id = os.environ["GOOGLE_FORM_ID"]
        self._service = self._build_service()

        # Build flat list of questions in order
        self._questions = [
            q
            for test in survey["tests"]
            for q in test["questions"]
        ]

    # ----------------------------------------------------------
    # Public
    # ----------------------------------------------------------

    def deploy(self):
        print(f"  Form ID: {self._form_id}")
        print(f"  Questions to update: {len(self._questions)}")

        # Fetch current form state
        form      = self._service.forms().get(formId=self._form_id).execute()
        items     = form.get("items", [])
        scale_items = [item for item in items if "scaleQuestion" in item.get("questionItem", {}).get("question", {})]

        print(f"  Current scale items in form: {len(scale_items)}")

        if len(scale_items) != len(self._questions):
            print(
                f"  ⚠️  Form has {len(scale_items)} scale questions "
                f"but JSON has {len(self._questions)}. "
                f"Manual form rebuild may be needed."
            )
            return

        # Build batch update requests
        requests   = []
        changed    = 0
        unchanged  = 0

        for i, (item, q) in enumerate(zip(scale_items, self._questions)):
            current_desc = item.get("description", "").strip()
            new_desc     = q["text"].strip()

            if current_desc == new_desc:
                unchanged += 1
                continue

            requests.append({
                "updateItem": {
                    "item": {
                        "itemId":      item["itemId"],
                        "title":       f"Câu {q['number']}",   # stable — always set
                        "description": new_desc,
                        "questionItem": item["questionItem"],
                    },
                    "location": {"index": item["index"] if "index" in item else i},
                    "updateMask": "title,description",
                }
            })
            changed += 1

        print(f"  Changed: {changed} | Unchanged: {unchanged}")

        if not requests:
            print("  ✅ No changes needed — form is already up to date")
            return

        # Execute in batches of 50 (API limit)
        batch_size = 50
        for batch_start in range(0, len(requests), batch_size):
            batch = requests[batch_start:batch_start + batch_size]
            self._service.forms().batchUpdate(
                formId=self._form_id,
                body={"requests": batch}
            ).execute()
            print(f"  Updated questions {batch_start + 1}–{batch_start + len(batch)}")
            time.sleep(0.5)   # avoid rate limiting

        print(f"  ✅ Form questions updated successfully")

    def check(self) -> bool:
        """
        Read-only comparison: does the live Google Form match survey JSON?
        Never modifies the form. Returns True if fully in sync.
        """
        print(f"  Form ID: {self._form_id}")
        print(f"  Questions in JSON: {len(self._questions)}")

        form        = self._service.forms().get(formId=self._form_id).execute()
        items       = form.get("items", [])
        scale_items = [item for item in items if "scaleQuestion" in item.get("questionItem", {}).get("question", {})]

        print(f"  Scale questions in live form: {len(scale_items)}")

        if len(scale_items) != len(self._questions):
            print(
                f"  ❌ Count mismatch — form has {len(scale_items)}, "
                f"JSON has {len(self._questions)}"
            )
            return False

        mismatches = []
        for i, (item, q) in enumerate(zip(scale_items, self._questions)):
            current_title = item.get("title", "").strip()
            current_desc  = item.get("description", "").strip()
            expected_title = f"Câu {q['number']}"
            expected_desc  = q["text"].strip()

            if current_title != expected_title:
                mismatches.append({
                    "number": q["number"],
                    "field": "title",
                    "form": current_title,
                    "json": expected_title,
                })
            if current_desc != expected_desc:
                mismatches.append({
                    "number": q["number"],
                    "field": "text",
                    "form": current_desc,
                    "json": expected_desc,
                })

        if not mismatches:
            print(f"  ✅ All {len(self._questions)} questions match exactly")
            return True

        print(f"  ❌ {len(mismatches)} mismatch(es) found:\n")
        for m in mismatches:
            print(f"  Câu {m['number']} ({m['field']}):")
            print(f"    Form: {m['form']!r}")
            print(f"    JSON: {m['json']!r}\n")

        return False

    # ----------------------------------------------------------
    # Private
    # ----------------------------------------------------------

    def _build_service(self):
        creds_path = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")
        if not creds_path:
            raise EnvironmentError("GOOGLE_SERVICE_ACCOUNT_JSON environment variable not set")

        creds = service_account.Credentials.from_service_account_file(
            creds_path, scopes=SCOPES
        )
        return build("forms", "v1", credentials=creds)
