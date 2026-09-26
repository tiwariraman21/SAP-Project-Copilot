from __future__ import annotations

import base64
import csv
import io
import json
import logging
import re
from datetime import datetime, timezone
from typing import Any

import httpx

from ..config import get_settings, settings
from ..models import Project
from .downstream import build_backlog, build_test_cases
from .project_identity import business_project_name


logger = logging.getLogger(__name__)


def _text_to_adf(text: str) -> dict[str, Any]:
    """Converts plain text or bulleted markdown into Atlassian Document Format (ADF)."""
    lines = text.strip().split("\n")
    content_blocks = []
    
    current_para = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if current_para:
                content_blocks.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": " ".join(current_para)}]
                })
                current_para = []
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            if current_para:
                content_blocks.append({
                    "type": "paragraph",
                    "content": [{"type": "text", "text": " ".join(current_para)}]
                })
                current_para = []
            content_blocks.append({
                "type": "bulletList",
                "content": [{
                    "type": "listItem",
                    "content": [{
                        "type": "paragraph",
                        "content": [{"type": "text", "text": stripped[2:].strip()}]
                    }]
                }]
            })
        else:
            current_para.append(stripped)
            
    if current_para:
        content_blocks.append({
            "type": "paragraph",
            "content": [{"type": "text", "text": " ".join(current_para)}]
        })
        
    if not content_blocks:
        content_blocks = [{
            "type": "paragraph",
            "content": [{"type": "text", "text": text or "SAP requirement delivery item"}]
        }]
        
    return {
        "type": "doc",
        "version": 1,
        "content": content_blocks
    }


def export_jira_csv(project: Project) -> str:
    """Generates an RFC 4180 CSV export formatted for standard Jira External System CSV Import."""
    backlog_artifact = next((a for a in project.artifacts if a.kind == "backlog"), None)
    if backlog_artifact and isinstance(backlog_artifact.payload, dict) and "stories" in backlog_artifact.payload:
        stories = backlog_artifact.payload.get("stories", [])
    else:
        generated = build_backlog(project)
        stories = generated.get("stories", [])

    display_name = business_project_name(project)
    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    # Standard Jira CSV Import column headers
    headers = [
        "Issue Type",
        "Summary",
        "Description",
        "Priority",
        "Story Points",
        "Sprint",
        "Epic Name",
        "Labels",
        "Requirement Key",
        "Acceptance Criteria",
        "Assigned Role",
        "Start Date",
        "Target End Date",
        "Source Evidence",
    ]
    writer.writerow(headers)

    for s in stories:
        req_key = s.get("requirement_key", "REQ")
        title = s.get("title", "")
        summary = f"[{req_key}] {title}"
        story_text = s.get("story", "")
        criteria = s.get("acceptance_criteria", [])
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "Standard SAP verification"
        assigned_role = s.get("assigned_to", "SAP Functional Consultant")
        source_loc = s.get("source_locator", "BRD")
        source_ev = s.get("source_evidence", "")

        description = (
            f"h3. User Story\n{story_text}\n\n"
            f"h3. Acceptance Criteria\n{criteria_text}\n\n"
            f"h3. Technical Context\n* *Role:* {assigned_role}\n* *Source Locator:* {source_loc}\n"
            + (f"* *BRD Quote:* {source_ev}\n" if source_ev else "")
        )

        priority = "High" if str(s.get("priority", "")).lower() == "must" else "Medium"
        story_points = s.get("story_points", 5 if priority == "High" else 3)
        sprint_val = f"Sprint {s.get('sprint', 1)}"
        labels = f"SAP-Fiori,ABAP-Cloud,BRD-Grounded,{req_key.replace('-', '_')}"

        writer.writerow([
            "Story",
            summary,
            description,
            priority,
            story_points,
            sprint_val,
            display_name,
            labels,
            req_key,
            criteria_text,
            assigned_role,
            s.get("start_date", ""),
            s.get("target_end_date", ""),
            source_ev,
        ])

    return output.getvalue()


def export_jira_test_cases_csv(project: Project) -> str:
    """Generates an RFC 4180 CSV export of quality test cases formatted for Jira / Zephyr / Xray CSV Import with QT standard codes."""
    test_artifact = next((a for a in project.artifacts if a.kind == "test_cases"), None)
    doc = test_artifact.payload.get("document", test_artifact.payload) if (test_artifact and isinstance(test_artifact.payload, dict)) else None
    if doc and isinstance(doc, dict) and "test_cases" in doc:
        test_cases = doc.get("test_cases", [])
    elif test_artifact and isinstance(test_artifact.payload, dict) and "test_cases" in test_artifact.payload:
        test_cases = test_artifact.payload.get("test_cases", [])
    else:
        generated = build_test_cases(project)
        test_cases = generated.get("test_cases", [])

    output = io.StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_MINIMAL)

    headers = [
        "Issue Type",
        "Summary",
        "Description",
        "Priority",
        "Labels",
        "Test Key",
        "Requirement Key",
        "Test Type",
        "Preconditions",
        "Execution Steps",
        "Expected Result",
        "Assigned To",
        "Status",
        "Source Evidence",
    ]
    writer.writerow(headers)

    for index, tc in enumerate(test_cases, 1):
        raw_key = str(tc.get("test_key") or f"QT-{index:03}")
        test_key = raw_key.replace("TC-", "QT-") if raw_key.startswith("TC-") else raw_key
        req_key = tc.get("requirement_key", "REQ")
        title = tc.get("title", "")
        summary = f"[{test_key}] {title} ({req_key})"
        preconditions = tc.get("preconditions", [])
        precond_text = "\n".join(f"- {p}" for p in preconditions) if preconditions else "Standard test role configured"
        steps = tc.get("steps", [])
        steps_text = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) if steps else f"Execute {req_key} test"
        expected = tc.get("expected_result", "System registers approved result")
        remarks = tc.get("remarks", "")
        source_ev = tc.get("source_evidence", "")

        description = (
            f"h3. Test Scenario & Objectives\nValidate approved SAP behavior for {req_key}.\n\n"
            f"h3. Preconditions\n{precond_text}\n\n"
            f"h3. Test Procedure / Execution Steps\n{steps_text}\n\n"
            f"h3. Expected Outcome / Verification Criteria\n{expected}\n\n"
            f"h3. Quality & Traceability Notes\n* *Test Key:* {test_key}\n"
            f"* *Requirement:* {req_key}\n"
            f"* *Test Type:* {tc.get('test_type', 'Functional')}\n"
            f"* *Assigned Tester:* {tc.get('assigned_to', 'QA Engineer')}\n"
            + (f"* *Remarks:* {remarks}\n" if remarks else "")
            + (f"* *BRD Quote:* {source_ev}\n" if source_ev else "")
        )

        p_str = str(tc.get("priority", "")).lower()
        priority = "High" if "must" in p_str or "high" in p_str else "Medium"
        labels = f"SAP-Quality,QA-Test-Pack,BRD-Grounded,{req_key.replace('-', '_')},{test_key.replace('-', '_')}"

        writer.writerow([
            "Test",
            summary,
            description,
            priority,
            labels,
            test_key,
            req_key,
            tc.get("test_type", "Functional"),
            precond_text,
            steps_text,
            expected,
            tc.get("assigned_to", "QA Engineer"),
            tc.get("status", "Not Run"),
            source_ev,
        ])

    return output.getvalue()


def _generate_jira_project_key(name: str) -> str:
    """Generates a clean 2 to 4 letter uppercase Jira Project Key from a business project name."""
    clean = re.sub(r"[^A-Za-z0-9 ]+", " ", name).strip()
    stopwords = {"the", "a", "an", "and", "for", "of", "in", "to", "on", "sap", "fiori", "solution", "business", "requirements", "document", "spec", "specification", "app", "application"}
    words = [w for w in clean.split() if w.lower() not in stopwords]
    if not words:
        words = [w for w in clean.split() if w.lower() not in {"the", "a", "an", "and", "for", "of", "in", "to", "on"}]
    if len(words) >= 3:
        key = "".join(w[0] for w in words[:4]).upper()
    elif len(words) == 2:
        key = (words[0][:2] + words[1][:2]).upper()
    elif len(words) == 1:
        key = words[0][:4].upper()
    else:
        key = "SAP"
    if len(key) < 2:
        key = (key + "PR")[:3]
    return key[:6]


class JiraClient:
    """Client for Atlassian Jira Cloud REST API v3 & Agile API."""

    def __init__(
        self,
        url: str | None = None,
        email: str | None = None,
        api_token: str | None = None,
        project_key: str | None = None,
    ):
        live_cfg = get_settings()
        self.url = (url or live_cfg.jira_url or "").rstrip("/")
        self.email = email or live_cfg.jira_email or ""
        self.api_token = api_token or live_cfg.jira_api_token or ""
        self.project_key = (project_key or live_cfg.jira_project_key or "").upper()

        if not self.url or not self.email or not self.api_token:
            raise ValueError(
                "Missing Jira credentials. Please provide Jira Site URL, Email, and Atlassian API Token."
            )

        auth_str = f"{self.email}:{self.api_token}"
        self.auth_header = f"Basic {base64.b64encode(auth_str.encode()).decode()}"
        self.headers = {
            "Authorization": self.auth_header,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._client = httpx.Client(timeout=20.0, headers=self.headers)

    def _request(
        self,
        method: str,
        path: str,
        json_body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        endpoint = f"{self.url}{path}"
        response = self._client.request(
            method=method,
            url=endpoint,
            json=json_body,
            params=params,
        )
        if response.status_code >= 400:
            error_msg = f"Jira API Error ({response.status_code}) on {method} {path}"
            try:
                err_json = response.json()
                if "errorMessages" in err_json and err_json["errorMessages"]:
                    error_msg += f": {', '.join(err_json['errorMessages'])}"
                elif "errors" in err_json and err_json["errors"]:
                    error_msg += f": {json.dumps(err_json['errors'])}"
                elif "message" in err_json:
                    error_msg += f": {err_json['message']}"
            except Exception:
                error_msg += f": {response.text[:200]}"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        if response.status_code == 204 or not response.content:
            return {}
        return response.json()

    def get_existing_issues_map(self) -> dict[str, Any]:
        """
        Fetches existing project issues from Jira Cloud to enable in-place updates.
        Returns structured lookup maps for epics, user stories, and test cases.
        """
        epics_map: dict[str, str] = {}
        stories_map: dict[str, str] = {}
        tests_map: dict[str, str] = {}

        start_at = 0
        max_results = 100
        next_page_token = None
        has_more = True

        while has_more:
            try:
                body: dict[str, Any] = {
                    "jql": f'project = "{self.project_key}" ORDER BY created ASC',
                    "fields": ["summary", "labels", "issuetype", "parent", "status"],
                    "maxResults": max_results,
                }
                if next_page_token:
                    body["nextPageToken"] = next_page_token

                try:
                    res = self._request("POST", "/rest/api/3/search/jql", json_body=body)
                except Exception:
                    # Fallback for Jira Server / older Cloud instances
                    res = self._request(
                        "GET",
                        "/rest/api/3/search",
                        params={
                            "jql": f'project = "{self.project_key}" ORDER BY created ASC',
                            "startAt": start_at,
                            "maxResults": max_results,
                            "fields": "summary,labels,issuetype,parent,status",
                        },
                    )

                issues = res.get("issues", [])
                if not issues:
                    break

                for issue in issues:
                    issue_key = issue.get("key") or issue.get("id")
                    fields = issue.get("fields", {})
                    summary = (fields.get("summary") or "").strip()
                    labels = [str(l).strip().lower() for l in fields.get("labels", [])]
                    itype = (fields.get("issuetype", {}).get("name") or "").lower()

                    # Check if Epic
                    if itype == "epic" or "solution delivery" in summary.lower() or "quality" in summary.lower():
                        epics_map[summary.lower()] = issue_key
                        if "delivery" in summary.lower() or "solution" in summary.lower():
                            epics_map["delivery"] = issue_key
                        if "quality" in summary.lower() or "test" in summary.lower():
                            epics_map["quality"] = issue_key

                    # Extract tags from summary e.g. [REQ-001], [US-001], [QT-001], [TC-001]
                    tags = re.findall(r"\[([A-Za-z0-9_-]+)\]", summary)
                    for tag in tags:
                        tag_norm = tag.upper()
                        if tag_norm.startswith("REQ-") or tag_norm.startswith("US-"):
                            stories_map[tag_norm] = issue_key
                        elif tag_norm.startswith("QT-") or tag_norm.startswith("TC-"):
                            tests_map[tag_norm] = issue_key
                            if tag_norm.startswith("TC-"):
                                tests_map[tag_norm.replace("TC-", "QT-")] = issue_key

                    # Extract keys from labels e.g. req_001, qt_001, tc_001, us_001
                    for lbl in labels:
                        lbl_upper = lbl.upper().replace("_", "-")
                        if lbl_upper.startswith("REQ-") or lbl_upper.startswith("US-"):
                            stories_map[lbl_upper] = issue_key
                        elif lbl_upper.startswith("QT-") or lbl_upper.startswith("TC-"):
                            tests_map[lbl_upper] = issue_key
                            if lbl_upper.startswith("TC-"):
                                tests_map[lbl_upper.replace("TC-", "QT-")] = issue_key

                next_page_token = res.get("nextPageToken")
                start_at += len(issues)
                if res.get("isLast", False) or not next_page_token or len(issues) < max_results:
                    has_more = False
            except Exception as e:
                logger.warning(f"Could not load existing issues for project {self.project_key}: {e}")
                break

        return {
            "epics": epics_map,
            "stories": stories_map,
            "tests": tests_map,
        }

    def get_existing_sprints(self, board_id: int) -> dict[str, int]:
        """Finds existing board sprints by name to avoid duplicate sprint creation."""
        sprints_map = {}
        try:
            res = self._request("GET", f"/rest/agile/1.0/board/{board_id}/sprint")
            values = res.get("values", [])
            for v in values:
                name = (v.get("name") or "").strip()
                sprints_map[name.lower()] = v.get("id")
        except Exception as e:
            logger.warning(f"Could not list sprints on board {board_id}: {e}")
        return sprints_map

    def get_or_create_project(self, display_name: str) -> tuple[str, str]:
        """Ensures the Jira project exists, creating it dynamically via Jira REST API if needed."""
        myself = self._request("GET", "/rest/api/3/myself")
        account_id = myself.get("accountId")

        # 1. Check existing projects list in Jira
        try:
            all_projs = self._request("GET", "/rest/api/3/project")
            if isinstance(all_projs, list):
                if self.project_key and self.project_key not in {"AUTO", "NEW", ""}:
                    for p in all_projs:
                        if p.get("key", "").upper() == self.project_key.upper():
                            self.project_key = p.get("key")
                            return self.project_key, p.get("name", display_name)
                
                disp_norm = display_name.lower().strip()
                for p in all_projs:
                    p_name = p.get("name", "").lower().strip()
                    if p_name == disp_norm or disp_norm in p_name or p_name in disp_norm:
                        self.project_key = p.get("key")
                        logger.info(f"Found existing Jira project '{p.get('name')}' with key {self.project_key}")
                        return self.project_key, p.get("name", display_name)
        except Exception as e:
            logger.warning(f"Could not list existing Jira projects: {e}")

        if not self.project_key or self.project_key in {"AUTO", "NEW", ""}:
            self.project_key = _generate_jira_project_key(display_name)

        # 2. Check if project key exists directly
        try:
            proj = self._request("GET", f"/rest/api/3/project/{self.project_key}")
            return self.project_key, proj.get("name", display_name)
        except Exception:
            logger.info(f"Project key {self.project_key} not found. Creating new Jira project dynamically...")

        # 3. Create new project dynamically via API
        project_payloads = [
            {
                "key": self.project_key,
                "name": display_name[:80],
                "projectTypeKey": "software",
                "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic",
                "description": f"Created dynamically by SAP Project Copilot for {display_name}",
                "leadAccountId": account_id,
                "assigneeType": "PROJECT_LEAD",
            },
            {
                "key": self.project_key,
                "name": f"{display_name[:70]} ({self.project_key})",
                "projectTypeKey": "software",
                "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-scrum-classic",
                "description": f"Created dynamically by SAP Project Copilot for {display_name}",
                "leadAccountId": account_id,
                "assigneeType": "PROJECT_LEAD",
            },
            {
                "key": self.project_key,
                "name": display_name[:80],
                "projectTypeKey": "software",
                "projectTemplateKey": "com.pyxis.greenhopper.jira:gh-simplified-agility-scrum",
                "description": f"Created dynamically by SAP Project Copilot for {display_name}",
                "leadAccountId": account_id,
            },
            {
                "key": self.project_key,
                "name": display_name[:80],
                "projectTypeKey": "software",
                "leadAccountId": account_id,
            },
        ]

        for p in project_payloads:
            try:
                created = self._request("POST", "/rest/api/3/project", json_body=p)
                logger.info(f"Successfully created Jira project {self.project_key} for {display_name}")
                return self.project_key, created.get("name", display_name)
            except Exception as e:
                logger.warning(f"Project creation attempt failed: {e}")

        return self.project_key, display_name

    def test_connection(self) -> dict[str, Any]:
        """Validates Jira connection and verifies access to the project."""
        myself = self._request("GET", "/rest/api/3/myself")
        user_name = myself.get("displayName") or myself.get("emailAddress") or "Atlassian User"

        project_name = None
        if self.project_key and self.project_key not in {"AUTO", "NEW"}:
            try:
                proj = self._request("GET", f"/rest/api/3/project/{self.project_key}")
                project_name = proj.get("name")
            except Exception:
                return {
                    "success": True,
                    "message": f"Connected as {user_name}. Target key [{self.project_key}] will be auto-created on first sync.",
                    "user_display_name": user_name,
                    "project_name": "Will be auto-created",
                    "project_key": self.project_key,
                }

        return {
            "success": True,
            "message": f"Successfully connected to Jira Cloud as {user_name}"
            + (f" (Project: {project_name} [{self.project_key}])" if project_name else " (Ready to auto-create project dynamically)"),
            "user_display_name": user_name,
            "project_name": project_name,
            "project_key": self.project_key or "AUTO",
        }

    def get_or_create_board(self) -> int | None:
        """Finds the agile Scrum or Kanban board for the project."""
        try:
            res = self._request("GET", "/rest/agile/1.0/board", params={"projectKeyOrId": self.project_key})
            values = res.get("values", [])
            if values:
                return values[0]["id"]
        except Exception as e:
            logger.warning(f"Could not retrieve Jira Agile board for project {self.project_key}: {e}")
        return None

    def create_or_update_epic(
        self,
        summary: str,
        description: str,
        existing_key: str | None = None,
    ) -> dict[str, Any] | None:
        """Creates or updates an Epic issue representing the overall SAP delivery initiative."""
        if existing_key:
            update_payload = {
                "fields": {
                    "summary": summary[:250],
                    "description": _text_to_adf(description),
                }
            }
            try:
                self._request("PUT", f"/rest/api/3/issue/{existing_key}", json_body=update_payload)
                logger.info(f"Updated existing Epic {existing_key} in-place")
                return {"key": existing_key, "id": existing_key, "updated": True}
            except Exception as e:
                logger.warning(f"Could not update existing Epic {existing_key}: {e}")

        payload = {
            "fields": {
                "project": {"key": self.project_key},
                "summary": summary[:250],
                "description": _text_to_adf(description),
                "issuetype": {"name": "Epic"},
                "labels": ["SAP-Copilot", "BRD-Grounded"],
            }
        }
        try:
            res = self._request("POST", "/rest/api/3/issue", json_body=payload)
            return {**res, "updated": False}
        except Exception:
            try:
                payload["fields"]["issuetype"] = {"name": "Task"}
                res = self._request("POST", "/rest/api/3/issue", json_body=payload)
                return {**res, "updated": False}
            except Exception as e:
                logger.warning(f"Could not create Epic in Jira: {e}")
                return None

    def create_sprint(self, board_id: int, name: str, start_date: str, end_date: str, goal: str) -> int | None:
        """Creates an agile Sprint on the Jira board."""
        payload = {
            "name": name,
            "originBoardId": board_id,
            "goal": goal,
        }
        if start_date:
            try:
                dt_start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
                payload["startDate"] = dt_start.isoformat()
            except Exception:
                pass
        if end_date:
            try:
                dt_end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
                payload["endDate"] = dt_end.isoformat()
            except Exception:
                pass

        try:
            res = self._request("POST", "/rest/agile/1.0/sprint", json_body=payload)
            return res.get("id")
        except Exception as e:
            logger.warning(f"Could not create Sprint '{name}' on board {board_id}: {e}")
            return None

    def add_issues_to_sprint(self, sprint_id: int, issue_keys: list[str]) -> bool:
        """Assigns multiple issues to an agile sprint."""
        if not issue_keys:
            return True
        try:
            self._request(
                "POST",
                f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                json_body={"issues": issue_keys},
            )
            return True
        except Exception as e:
            logger.warning(f"Could not assign issues {issue_keys} to sprint {sprint_id}: {e}")
            return False

    def create_or_update_story(
        self,
        story: dict[str, Any],
        existing_key: str | None = None,
        epic_key: str | None = None,
        sprint_id: int | None = None,
    ) -> dict[str, Any]:
        """Creates or updates a Story in Jira and optionally links to Epic / Sprint."""
        req_key = story.get("requirement_key", "REQ")
        story_key = story.get("story_key", "US")
        title = story.get("title", "")
        summary = f"[{req_key}] {title}"[:250]
        story_text = story.get("story", "")
        criteria = story.get("acceptance_criteria", [])
        criteria_text = "\n".join(f"- {c}" for c in criteria) if criteria else "Standard SAP verification"
        assigned_role = story.get("assigned_to", "SAP Functional Consultant")
        source_loc = story.get("source_locator", "BRD")
        source_ev = story.get("source_evidence", "")

        desc_text = (
            f"User Story:\n{story_text}\n\n"
            f"Acceptance Criteria:\n{criteria_text}\n\n"
            f"Technical Implementation Context:\n"
            f"- Assigned Role: {assigned_role}\n"
            f"- Source Locator: {source_loc}\n"
            + (f"- BRD Quote: {source_ev}\n" if source_ev else "")
        )

        priority_name = "High" if str(story.get("priority", "")).lower() == "must" else "Medium"
        labels = ["SAP-Fiori", "ABAP-Cloud", "BRD-Grounded", req_key.replace("-", "_"), story_key.replace("-", "_")]

        fields: dict[str, Any] = {
            "summary": summary,
            "description": _text_to_adf(desc_text),
            "priority": {"name": priority_name},
            "labels": labels,
        }

        issue_key = None
        issue_id = None
        is_updated = False

        if existing_key:
            try:
                self._request("PUT", f"/rest/api/3/issue/{existing_key}", json_body={"fields": fields})
                issue_key = existing_key
                issue_id = existing_key
                is_updated = True
                logger.info(f"Successfully updated existing Story {existing_key} in-place")
            except Exception as e:
                logger.warning(f"Could not update existing story {existing_key}: {e}. Creating new issue...")
                existing_key = None

        if not existing_key:
            fields["project"] = {"key": self.project_key}
            fields["issuetype"] = {"name": "Story"}
            if epic_key:
                fields["parent"] = {"key": epic_key}
            try:
                issue_res = self._request("POST", "/rest/api/3/issue", json_body={"fields": fields})
            except Exception:
                fields["issuetype"] = {"name": "Task"}
                issue_res = self._request("POST", "/rest/api/3/issue", json_body={"fields": fields})
            issue_key = issue_res.get("key")
            issue_id = issue_res.get("id")
            is_updated = False

        if issue_key and sprint_id:
            try:
                self._request(
                    "POST",
                    f"/rest/agile/1.0/sprint/{sprint_id}/issue",
                    json_body={"issues": [issue_key]},
                )
            except Exception as e:
                logger.warning(f"Could not assign issue {issue_key} to sprint {sprint_id}: {e}")

        return {
            "issue_key": issue_key,
            "issue_id": issue_id,
            "issue_url": f"{self.url}/browse/{issue_key}" if issue_key else None,
            "story_key": story_key,
            "requirement_key": req_key,
            "title": title,
            "updated": is_updated,
        }

    def sync_project_backlog(
        self,
        project: Project,
        create_epic: bool = True,
        create_sprints: bool = True,
    ) -> dict[str, Any]:
        """Orchestrates end-to-end sync of project backlog stories and sprints into Jira with in-place updates."""
        backlog_artifact = next((a for a in project.artifacts if a.kind == "backlog"), None)
        if backlog_artifact and isinstance(backlog_artifact.payload, dict) and "stories" in backlog_artifact.payload:
            backlog = backlog_artifact.payload
        else:
            backlog = build_backlog(project)

        stories = backlog.get("stories", [])
        sprint_defs = backlog.get("sprints", [])
        display_name = business_project_name(project)
        self.get_or_create_project(display_name)

        existing_maps = self.get_existing_issues_map()
        existing_epics = existing_maps.get("epics", {})
        existing_stories = existing_maps.get("stories", {})

        epic_key = None
        epic_url = None
        if create_epic:
            epic_summary = f"{display_name} — SAP Solution Delivery"
            epic_desc = f"Generated by SAP Project Copilot from approved BRD '{project.document.filename if project.document else display_name}'. Contains {len(stories)} delivery user stories across {len(sprint_defs)} sprints."
            existing_epic_key = existing_epics.get(epic_summary.lower()) or existing_epics.get("delivery")
            epic_res = self.create_or_update_epic(epic_summary, epic_desc, existing_key=existing_epic_key)
            if epic_res and "key" in epic_res:
                epic_key = epic_res["key"]
                epic_url = f"{self.url}/browse/{epic_key}"

        board_id = self.get_or_create_board() if create_sprints else None
        board_url = f"{self.url}/jira/software/c/projects/{self.project_key}/boards/{board_id}" if board_id else f"{self.url}/browse/{self.project_key}"

        existing_sprints_map = self.get_existing_sprints(board_id) if board_id else {}
        sprint_map: dict[int, int] = {}
        sprints_created_count = 0
        if board_id and create_sprints:
            for sp in sprint_defs:
                sp_num = sp.get("number", 1)
                sp_name = f"{self.project_key} Sprint {sp_num}"[:28]
                existing_sp_id = existing_sprints_map.get(sp_name.lower())
                if existing_sp_id:
                    sprint_map[sp_num] = existing_sp_id
                else:
                    sp_id = self.create_sprint(
                        board_id=board_id,
                        name=sp_name,
                        start_date=sp.get("start_date", ""),
                        end_date=sp.get("target_end_date", ""),
                        goal=sp.get("goal", f"Deliver sprint {sp_num} user stories")[:250],
                    )
                    if sp_id:
                        sprint_map[sp_num] = sp_id
                        sprints_created_count += 1

        synced_stories = []
        sprint_issues_map: dict[int, list[str]] = {}
        for s in stories:
            req_key = s.get("requirement_key", "REQ")
            story_key = s.get("story_key", "US")
            existing_key = (
                s.get("jira_key")
                or existing_stories.get(req_key)
                or existing_stories.get(story_key)
            )
            sp_num = s.get("sprint", 1)
            target_sprint_id = sprint_map.get(sp_num)
            res = self.create_or_update_story(story=s, existing_key=existing_key, epic_key=epic_key, sprint_id=None)
            synced_stories.append(res)
            issue_key = res.get("issue_key")
            if issue_key and target_sprint_id:
                sprint_issues_map.setdefault(target_sprint_id, []).append(issue_key)
            s["jira_key"] = issue_key
            s["jira_url"] = res.get("issue_url")

        for sprint_id, issue_keys in sprint_issues_map.items():
            if issue_keys:
                self.add_issues_to_sprint(sprint_id, issue_keys)

        if backlog_artifact and isinstance(backlog_artifact.payload, dict):
            backlog_artifact.payload = {
                **backlog_artifact.payload,
                "stories": stories,
                "jira_sync": {
                    "synced_at": datetime.now(timezone.utc).isoformat(),
                    "jira_url": self.url,
                    "project_key": self.project_key,
                    "epic_key": epic_key,
                    "epic_url": epic_url,
                    "board_url": board_url,
                    "stories_synced": len(synced_stories),
                    "sprints_synced": len(sprint_map),
                },
            }

        updated_count = sum(1 for item in synced_stories if item.get("updated"))
        created_count = len(synced_stories) - updated_count

        return {
            "success": True,
            "message": f"Successfully synchronized {len(synced_stories)} User Stories"
            + (f" ({updated_count} updated in-place, {created_count} created)" if updated_count else "")
            + (f" to Epic {epic_key}" if epic_key else "")
            + (f" across {len(sprint_map)} Sprints" if sprint_map else "")
            + f" in Jira project {self.project_key}.",
            "jira_url": self.url,
            "project_key": self.project_key,
            "epic_key": epic_key,
            "epic_url": epic_url,
            "sprints_created": len(sprint_map),
            "stories_created": len(synced_stories),
            "board_url": board_url,
            "synced_stories": synced_stories,
        }

    def create_or_update_test_case(
        self,
        test_case: dict[str, Any],
        existing_key: str | None = None,
        epic_key: str | None = None,
    ) -> dict[str, Any]:
        """Creates or updates a Test Case issue in Jira linked to the parent Epic using QT- standard code."""
        raw_key = str(test_case.get("test_key") or "QT-001")
        test_key = raw_key.replace("TC-", "QT-") if raw_key.startswith("TC-") else raw_key
        if not test_key.startswith("QT-"):
            test_key = f"QT-{test_key.lstrip('0123456789-')}" if not test_key.startswith("QT") else test_key
        test_case["test_key"] = test_key

        req_key = test_case.get("requirement_key", "REQ")
        title = test_case.get("title", "")
        summary = f"[{test_key}] {title} ({req_key})"[:250]
        
        preconditions = test_case.get("preconditions", [])
        precond_text = "\n".join(f"- {p}" for p in preconditions) if preconditions else "Standard test role configured"
        steps = test_case.get("steps", [])
        steps_text = "\n".join(f"{i}. {s}" for i, s in enumerate(steps, 1)) if steps else f"Execute {req_key} test"
        expected = test_case.get("expected_result", "System registers approved result")
        remarks = test_case.get("remarks", "")
        source_ev = test_case.get("source_evidence", "")

        desc_text = (
            f"Test Scenario & Objectives:\nValidate approved SAP behavior for {req_key}.\n\n"
            f"Preconditions:\n{precond_text}\n\n"
            f"Execution Steps:\n{steps_text}\n\n"
            f"Expected Outcome:\n{expected}\n\n"
            f"Quality & Traceability Context:\n"
            f"- Test Key: {test_key}\n"
            f"- Requirement: {req_key}\n"
            f"- Test Type: {test_case.get('test_type', 'Functional')}\n"
            f"- Assigned Tester: {test_case.get('assigned_to', 'QA Engineer')}\n"
            + (f"- Remarks: {remarks}\n" if remarks else "")
            + (f"- BRD Evidence: {source_ev}\n" if source_ev else "")
        )

        p_str = str(test_case.get("priority", "")).lower()
        priority_name = "High" if "must" in p_str or "high" in p_str else "Medium"
        labels = ["SAP-Quality", "QA-Test-Pack", "BRD-Grounded", req_key.replace("-", "_"), test_key.replace("-", "_")]

        fields: dict[str, Any] = {
            "summary": summary,
            "description": _text_to_adf(desc_text),
            "priority": {"name": priority_name},
            "labels": labels,
        }

        issue_key = None
        issue_id = None
        is_updated = False

        if existing_key:
            try:
                self._request("PUT", f"/rest/api/3/issue/{existing_key}", json_body={"fields": fields})
                issue_key = existing_key
                issue_id = existing_key
                is_updated = True
                logger.info(f"Successfully updated existing Test Case {existing_key} [{test_key}] in-place")
            except Exception as e:
                logger.warning(f"Could not update existing test case {existing_key}: {e}. Creating new issue...")
                existing_key = None

        if not existing_key:
            issue_type_name = getattr(self, "_resolved_test_issue_type", None) or "Test"
            fields["project"] = {"key": self.project_key}
            fields["issuetype"] = {"name": issue_type_name}
            if epic_key:
                fields["parent"] = {"key": epic_key}
            try:
                issue_res = self._request("POST", "/rest/api/3/issue", json_body={"fields": fields})
                self._resolved_test_issue_type = issue_type_name
            except Exception:
                fields["issuetype"] = {"name": "Task"}
                issue_res = self._request("POST", "/rest/api/3/issue", json_body={"fields": fields})
                self._resolved_test_issue_type = "Task"
            issue_key = issue_res.get("key")
            issue_id = issue_res.get("id")
            is_updated = False

        return {
            "issue_key": issue_key,
            "issue_id": issue_id,
            "issue_url": f"{self.url}/browse/{issue_key}" if issue_key else None,
            "test_key": test_key,
            "requirement_key": req_key,
            "title": title,
            "updated": is_updated,
        }

    def sync_project_test_cases(
        self,
        project: Project,
        create_epic: bool = True,
    ) -> dict[str, Any]:
        """Orchestrates end-to-end sync of project test cases into Jira with in-place updates and QT- standard codes."""
        test_artifact = next((a for a in project.artifacts if a.kind == "test_cases"), None)
        doc = test_artifact.payload.get("document", test_artifact.payload) if (test_artifact and isinstance(test_artifact.payload, dict)) else None
        if doc and isinstance(doc, dict) and "test_cases" in doc:
            payload = doc
        elif test_artifact and isinstance(test_artifact.payload, dict) and "test_cases" in test_artifact.payload:
            payload = test_artifact.payload
        else:
            payload = build_test_cases(project)

        test_cases = payload.get("test_cases", [])
        display_name = business_project_name(project)
        self.get_or_create_project(display_name)

        existing_maps = self.get_existing_issues_map()
        existing_epics = existing_maps.get("epics", {})
        existing_tests = existing_maps.get("tests", {})

        epic_key = None
        epic_url = None
        if create_epic:
            epic_summary = f"{display_name} — Quality & Test Execution Pack"
            epic_desc = f"Generated by SAP Project Copilot from approved BRD '{project.document.filename if project.document else display_name}'. Contains {len(test_cases)} QA test verification cases."
            existing_epic_key = existing_epics.get(epic_summary.lower()) or existing_epics.get("quality")
            epic_res = self.create_or_update_epic(epic_summary, epic_desc, existing_key=existing_epic_key)
            if epic_res and "key" in epic_res:
                epic_key = epic_res["key"]
                epic_url = f"{self.url}/browse/{epic_key}"

        board_id = self.get_or_create_board()
        board_url = f"{self.url}/jira/software/c/projects/{self.project_key}/boards/{board_id}" if board_id else f"{self.url}/browse/{self.project_key}"

        synced_tests = []
        for index, tc in enumerate(test_cases, 1):
            raw_key = str(tc.get("test_key") or f"QT-{index:03}")
            test_key = raw_key.replace("TC-", "QT-") if raw_key.startswith("TC-") else raw_key
            tc["test_key"] = test_key
            req_key = tc.get("requirement_key", "REQ")

            existing_key = (
                tc.get("jira_key")
                or existing_tests.get(test_key)
                or existing_tests.get(raw_key)
                or existing_tests.get(req_key)
            )
            res = self.create_or_update_test_case(test_case=tc, existing_key=existing_key, epic_key=epic_key)
            synced_tests.append(res)
            tc["jira_key"] = res.get("issue_key")
            tc["jira_url"] = res.get("issue_url")

        if test_artifact and isinstance(test_artifact.payload, dict):
            if isinstance(test_artifact.payload.get("document"), dict):
                test_artifact.payload["document"]["test_cases"] = test_cases
            else:
                test_artifact.payload["test_cases"] = test_cases
            test_artifact.payload["jira_sync"] = {
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "jira_url": self.url,
                "project_key": self.project_key,
                "epic_key": epic_key,
                "epic_url": epic_url,
                "board_url": board_url,
                "tests_synced": len(synced_tests),
            }

        updated_count = sum(1 for item in synced_tests if item.get("updated"))
        created_count = len(synced_tests) - updated_count

        return {
            "success": True,
            "message": f"Successfully synchronized {len(synced_tests)} Test Cases"
            + (f" ({updated_count} updated in-place, {created_count} created)" if updated_count else "")
            + (f" to Epic {epic_key}" if epic_key else "")
            + f" in Jira project {self.project_key}.",
            "jira_url": self.url,
            "project_key": self.project_key,
            "epic_key": epic_key,
            "epic_url": epic_url,
            "tests_created": len(synced_tests),
            "board_url": board_url,
            "synced_tests": synced_tests,
        }
