import csv
import io
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models import ReviewStatus
from app.services.downstream import build_backlog, build_test_cases
from app.services.jira_sync import JiraClient, export_jira_csv, export_jira_test_cases_csv

client = TestClient(app)


def _requirement(**overrides):
    base = dict(
        requirement_key="REQ-001",
        title="Supplier Purchase Order Selection",
        statement="The supplier shall select an eligible purchase order for gate pass creation.",
        requirement_type="functional",
        priority="must",
        acceptance_criteria=["PO is selected and verified", "Valid lines displayed"],
        source_chunk_ids=["chunk-1"],
        source_quote="The supplier shall select an eligible purchase order.",
        review_status=ReviewStatus.approved,
        rationale="",
        assumptions=[],
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _project():
    chunk = SimpleNamespace(id="chunk-1", locator="Page 7")
    document = SimpleNamespace(filename="Gate_Pass_Application_BRD.pdf", chunks=[chunk])
    project = SimpleNamespace(
        id="proj-jira-test",
        name="Gate Pass Application",
        created_at=datetime(2026, 8, 31),
        document=document,
        requirements=[
            _requirement(requirement_key="REQ-001", title="PO Search and Selection", priority="must"),
            _requirement(requirement_key="REQ-002", title="Transporter Details Entry", priority="must"),
            _requirement(requirement_key="REQ-003", title="Approver Inbox L1 Review", priority="should"),
            _requirement(requirement_key="REQ-004", title="Gate Security QR Verification", priority="must"),
        ],
        artifacts=[],
    )
    backlog = build_backlog(project)
    test_cases = build_test_cases(project)
    project.artifacts = [
        SimpleNamespace(kind="backlog", status="generated", payload=backlog),
        SimpleNamespace(kind="test_cases", status="generated", payload=test_cases),
    ]
    return project


def test_export_jira_csv_structure():
    project = _project()
    csv_text = export_jira_csv(project)
    assert csv_text
    
    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) == 5  # header + 4 stories
    header = rows[0]
    assert "Issue Type" in header
    assert "Summary" in header
    assert "Description" in header
    assert "Priority" in header
    assert "Story Points" in header
    assert "Sprint" in header
    assert "Epic Name" in header

    # Verify first row
    first_story = rows[1]
    assert first_story[0] == "Story"
    assert "[REQ-001]" in first_story[1]
    assert first_story[3] == "High"  # must have -> High
    assert first_story[4] == "5"     # 5 story points


def test_export_jira_test_cases_csv_structure():
    project = _project()
    csv_text = export_jira_test_cases_csv(project)
    assert csv_text

    reader = csv.reader(io.StringIO(csv_text))
    rows = list(reader)
    assert len(rows) > 1
    header = rows[0]
    assert "Issue Type" in header
    assert "Summary" in header
    assert "Test Key" in header
    assert "Requirement Key" in header

    first_test = rows[1]
    assert first_test[0] == "Test"
    assert "[QT-001]" in first_test[1]
    assert first_test[5] == "QT-001"
    assert "QT_001" in first_test[4]


def test_jira_client_test_connection_mocked():
    with patch("httpx.Client.request") as mock_req:
        # Mock /rest/api/3/myself
        mock_resp1 = MagicMock()
        mock_resp1.status_code = 200
        mock_resp1.json.return_value = {"displayName": "John Doe", "emailAddress": "john@example.com"}
        mock_resp1.content = b'{"displayName": "John Doe"}'

        # Mock /rest/api/3/project/GP
        mock_resp2 = MagicMock()
        mock_resp2.status_code = 200
        mock_resp2.json.return_value = {"key": "GP", "name": "Gate Pass SAP Project"}
        mock_resp2.content = b'{"key": "GP", "name": "Gate Pass SAP Project"}'

        mock_req.side_effect = [mock_resp1, mock_resp2]

        jira = JiraClient(
            url="https://test.atlassian.net",
            email="john@example.com",
            api_token="dummy-token",
            project_key="GP",
        )
        res = jira.test_connection()
        assert res["success"] is True
        assert res["user_display_name"] == "John Doe"
        assert res["project_name"] == "Gate Pass SAP Project"


def test_jira_client_sync_project_backlog_mocked():
    project = _project()
    with patch("httpx.Client.request") as mock_req:
        # 0. Myself & Project Lookup
        resp_myself = MagicMock(status_code=200, content=b'{"accountId": "acc-123", "displayName": "John Doe"}')
        resp_myself.json.return_value = {"accountId": "acc-123", "displayName": "John Doe"}

        resp_project = MagicMock(status_code=200, content=b'[{"key": "GP", "name": "Gate Pass Application"}]')
        resp_project.json.return_value = [{"key": "GP", "name": "Gate Pass Application"}]

        # Existing issues search
        resp_search = MagicMock(status_code=200, content=b'{"total": 0, "issues": []}')
        resp_search.json.return_value = {"total": 0, "issues": []}

        # 1. Create Epic
        resp_epic = MagicMock(status_code=201, content=b'{"key": "GP-100"}')
        resp_epic.json.return_value = {"key": "GP-100", "id": "10100"}

        # 2. Get Board
        resp_board = MagicMock(status_code=200, content=b'{"values": [{"id": 42}]}')
        resp_board.json.return_value = {"values": [{"id": 42}]}

        # Sprints list
        resp_sprints_list = MagicMock(status_code=200, content=b'{"values": []}')
        resp_sprints_list.json.return_value = {"values": []}

        # 3. Create Sprints
        resp_sprint = MagicMock(status_code=201, content=b'{"id": 101}')
        resp_sprint.json.return_value = {"id": 101}

        # 4. Create Stories (4 stories)
        resp_story1 = MagicMock(status_code=201, content=b'{"key": "GP-101", "id": "10101"}')
        resp_story1.json.return_value = {"key": "GP-101", "id": "10101"}

        resp_assign = MagicMock(status_code=204, content=b'')

        mock_req.side_effect = [
            resp_myself,
            resp_project,
            resp_search,
            resp_epic,
            resp_board,
            resp_sprints_list,
            resp_sprint,
            resp_story1,
            resp_story1,
            resp_story1,
            resp_story1,
            resp_assign,
        ]

        jira = JiraClient(
            url="https://test.atlassian.net",
            email="john@example.com",
            api_token="dummy-token",
            project_key="GP",
        )
        sync_res = jira.sync_project_backlog(project, create_epic=True, create_sprints=True)
        assert sync_res["success"] is True
        assert sync_res["epic_key"] == "GP-100"
        assert sync_res["stories_created"] == 4
        assert len(sync_res["synced_stories"]) == 4


def test_jira_client_sync_project_test_cases_update_in_place():
    project = _project()
    with patch("httpx.Client.request") as mock_req:
        # Myself & Project lookup
        resp_myself = MagicMock(status_code=200, content=b'{"accountId": "acc-123", "displayName": "John Doe"}')
        resp_myself.json.return_value = {"accountId": "acc-123", "displayName": "John Doe"}

        resp_project = MagicMock(status_code=200, content=b'[{"key": "GP", "name": "Gate Pass Application"}]')
        resp_project.json.return_value = [{"key": "GP", "name": "Gate Pass Application"}]

        # Existing search returns existing Epic and existing QT-001
        resp_search = MagicMock(status_code=200, content=b'{"total": 2}')
        resp_search.json.return_value = {
            "total": 2,
            "issues": [
                {
                    "key": "GP-50",
                    "fields": {
                        "summary": "Gate Pass Application — Quality & Test Execution Pack",
                        "issuetype": {"name": "Epic"},
                        "labels": ["SAP-Copilot"],
                    },
                },
                {
                    "key": "GP-51",
                    "fields": {
                        "summary": "[QT-001] Validate PO Search and Selection (REQ-001)",
                        "issuetype": {"name": "Task"},
                        "labels": ["SAP-Quality", "QT_001", "REQ_001"],
                    },
                },
            ],
        }

        # Update Epic PUT (GP-50)
        resp_put_epic = MagicMock(status_code=204, content=b'')

        # Get Board
        resp_board = MagicMock(status_code=200, content=b'{"values": [{"id": 42}]}')
        resp_board.json.return_value = {"values": [{"id": 42}]}

        # Update existing QT-001 via PUT (GP-51)
        resp_put_qt1 = MagicMock(status_code=204, content=b'')

        # Create new QT-002, QT-003, etc. via POST
        resp_create_test = MagicMock(status_code=201, content=b'{"key": "GP-52", "id": "10052"}')
        resp_create_test.json.return_value = {"key": "GP-52", "id": "10052"}

        mock_req.side_effect = [
            resp_myself,
            resp_project,
            resp_search,
            resp_put_epic,
            resp_board,
            resp_put_qt1,
            resp_create_test,
            resp_create_test,
            resp_create_test,
            resp_create_test,
            resp_create_test,
            resp_create_test,
            resp_create_test,
        ]

        jira = JiraClient(
            url="https://test.atlassian.net",
            email="john@example.com",
            api_token="dummy-token",
            project_key="GP",
        )
        sync_res = jira.sync_project_test_cases(project, create_epic=True)
        assert sync_res["success"] is True
        assert sync_res["epic_key"] == "GP-50"
        # First test was updated in-place
        assert sync_res["synced_tests"][0]["issue_key"] == "GP-51"
        assert sync_res["synced_tests"][0]["updated"] is True
        assert sync_res["synced_tests"][0]["test_key"] == "QT-001"
