import io
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import app.main as main_module
from app.config import settings
from app.main import app


settings.openai_api_key = None  # Tests must never consume API credits.
client = TestClient(app)


def test_vertical_slice():
    response = client.post("/api/projects", data={"name": "Order to Cash"}, files={"file": ("brd.txt", io.BytesIO(b"The system must validate customer credit before releasing a sales order.\n\nThe solution shall record the approval decision for audit reporting."), "text/plain")})
    assert response.status_code == 200
    project = response.json()
    assert len(project["requirements"]) == 2
    assert project["requirements"][0]["source_chunk_ids"]
    response = client.post(f"/api/projects/{project['id']}/requirements/approve-all")
    assert response.status_code == 200
    assert all(req["review_status"] == "approved" for req in response.json()["requirements"])
    response = client.post(f"/api/projects/{project['id']}/approve")
    assert response.status_code == 200
    assert response.json()["status"] == "approved"
    assert len(response.json()["artifacts"]) == 6
    fsd_status = client.get(f"/api/projects/{project['id']}/artifacts/fsd/processing-status")
    assert fsd_status.status_code == 200
    assert fsd_status.json()["status"] == "completed"
    assert client.get(f"/api/projects/{project['id']}/artifacts/fsd/download/docx").status_code == 200
    assert client.get(f"/api/projects/{project['id']}/artifacts/fsd/download/pdf").status_code == 200
    for kind in ["fsd", "backlog", "technical_design", "test_cases", "traceability", "companion"]:
        response = client.post(f"/api/projects/{project['id']}/artifacts/{kind}")
        assert response.status_code == 200
        artifact = next(a for a in response.json()["artifacts"] if a["kind"] == kind)
        assert artifact["status"] == "generated"
        assert artifact["payload"]["document"]["title"]
        if kind == "backlog":
            assert artifact["payload"]["downloads"]["xlsx"].endswith("/download/xlsx")
            assert "Anurag" not in artifact["payload"]["document"]["project_name"]
            workbook = client.get(f"/api/projects/{project['id']}/artifacts/backlog/download/xlsx")
            assert workbook.status_code == 200
            assert workbook.content[:2] == b"PK"
            suggested = client.post(f"/api/projects/{project['id']}/artifacts/backlog/resource-distribution")
            assert suggested.status_code == 200
            backlog = next(a for a in suggested.json()["artifacts"] if a["kind"] == "backlog")
            people = backlog["payload"]["resource_distribution"]["people"]
            assert people
            assert any(item["role"] == "Fiori Developer" for item in people)
            assert all("experience_years" in item for item in people)
            resources_xlsx = client.get(f"/api/projects/{project['id']}/artifacts/backlog/resource-distribution/xlsx")
            assert resources_xlsx.status_code == 200
            assert resources_xlsx.content[:2] == b"PK"
        if kind == "technical_design":
            tdd = client.get(f"/api/projects/{project['id']}/artifacts/technical_design/download/docx")
            assert tdd.status_code == 200
            assert tdd.content[:2] == b"PK"
            tdd_pdf = client.get(f"/api/projects/{project['id']}/artifacts/technical_design/download/pdf")
            assert tdd_pdf.status_code == 200
            assert tdd_pdf.content[:4] == b"%PDF"
            generated = client.post(f"/api/projects/{project['id']}/artifacts/technical_design/starter-code")
            assert generated.status_code == 200
            technical = next(a for a in generated.json()["artifacts"] if a["kind"] == "technical_design")
            assert technical["payload"]["starter_code"]["requirement_count"] == 2
            archive_response = client.get(f"/api/projects/{project['id']}/artifacts/technical_design/starter-code/download")
            assert archive_response.status_code == 200
            with zipfile.ZipFile(io.BytesIO(archive_response.content)) as archive:
                names = archive.namelist()
                assert any(name.endswith("/fiori/webapp/manifest.json") for name in names)
                assert any(name.endswith("/abap/src/zcl_ordertocash_service.clas.abap") for name in names)
                assert any(name.endswith("/docs/requirements.json") for name in names)
        if kind == "companion":
            fields = client.post(f"/api/projects/{project['id']}/companion/ask", json={"question": "What all fields will be there in my initial page?"})
            assert fields.status_code == 200
            assert "Overview" in fields.json()["answer"] or "field" in fields.json()["answer"].lower()
            assert any(source["kind"] == "fsd" for source in fields.json()["sources"])
            progress = client.post(f"/api/projects/{project['id']}/companion/ask", json={"question": "what is my current progress status in Functional area?"})
            assert progress.status_code == 200
            assert any(source["kind"] == "backlog" for source in progress.json()["sources"])
            assert progress.json()["project_id"] == project["id"]
        if kind == "test_cases":
            assert artifact["payload"]["downloads"]["xlsx"].endswith("/download/xlsx")
            title = artifact["payload"]["document"]["title"]
            assert title
            assert "Anurag" not in title
            assert not title.lower().startswith("quality test pack")
            assert all(
                case["priority"] in {"Must Have", "Good To Have", "Nice To Have", "Won't Have"}
                for case in artifact["payload"]["document"]["test_cases"]
            )
            workbook = client.get(f"/api/projects/{project['id']}/artifacts/test_cases/download/xlsx")
            assert workbook.status_code == 200
            assert workbook.content[:2] == b"PK"
            with zipfile.ZipFile(io.BytesIO(workbook.content)) as archive:
                text = "\n".join(
                    archive.read(name).decode("utf-8", errors="ignore")
                    for name in archive.namelist()
                    if name.endswith(".xml")
                )
            assert title in text
            assert "Must Have" in text
            assert "Quality Test Pack - Anurag" not in text


def test_resource_distribution_excel_without_generated_plan():
    response = client.post(
        "/api/projects",
        data={"name": "Order to Cash"},
        files={"file": ("brd.txt", io.BytesIO(b"The system must validate customer credit before releasing a sales order."), "text/plain")},
    )
    assert response.status_code == 200
    project = response.json()
    assert client.post(f"/api/projects/{project['id']}/requirements/approve-all").status_code == 200
    assert client.post(f"/api/projects/{project['id']}/approve").status_code == 200
    suggested = client.post(f"/api/projects/{project['id']}/artifacts/backlog/resource-distribution")
    assert suggested.status_code == 200
    backlog = next(a for a in suggested.json()["artifacts"] if a["kind"] == "backlog")
    people = backlog["payload"]["resource_distribution"]["people"]
    assert people
    assert backlog["payload"]["downloads"]["resources_xlsx"].endswith("/resource-distribution/xlsx")
    workbook = client.get(f"/api/projects/{project['id']}/artifacts/backlog/resource-distribution/xlsx")
    assert workbook.status_code == 200
    assert workbook.content[:2] == b"PK"
    reloaded = client.get(f"/api/projects/{project['id']}")
    assert reloaded.status_code == 200
    saved = next(a for a in reloaded.json()["artifacts"] if a["kind"] == "backlog")
    assert saved["payload"]["resource_distribution"]["people"]


def test_two_uploads_do_not_lock_sqlite(monkeypatch):
    original_extract = main_module.extract_requirements

    def delayed_extract(chunks):
        time.sleep(0.4)
        return original_extract(chunks)

    monkeypatch.setattr(main_module, "extract_requirements", delayed_extract)

    def upload(index: int):
        with TestClient(app) as test_client:
            return test_client.post(
                "/api/projects",
                data={"name": f"Concurrent project {index}"},
                files={"file": (f"brd-{index}.txt", io.BytesIO(b"The system must display the supplier status."), "text/plain")},
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = list(executor.map(upload, [1, 2]))

    assert [response.status_code for response in responses] == [200, 200]


def test_background_analysis_exposes_progress_logs():
    with TestClient(app) as test_client:
        response = test_client.post(
            "/api/projects/start",
            data={"name": "Observable analysis"},
            files={"file": ("observable-brd.txt", io.BytesIO(b"The system must show the current supplier status."), "text/plain")},
        )
        assert response.status_code == 202
        project_id = response.json()["project_id"]
        status = test_client.get(f"/api/projects/{project_id}/processing-status")
        assert status.status_code == 200
        payload = status.json()
        assert payload["status"] == "completed"
        assert payload["progress"] == 100
        assert any("Analysis complete" in entry["message"] for entry in payload["logs"])


def test_add_modify_and_delete_requirement():
    with TestClient(app) as test_client:
        upload_resp = test_client.post(
            "/api/projects",
            data={"name": "Requirement CRUD Test"},
            files={"file": ("crud-brd.txt", io.BytesIO(b"The system must validate purchase requests."), "text/plain")},
        )
        assert upload_resp.status_code == 200
        project = upload_resp.json()
        project_id = project["id"]
        initial_req_count = len(project["requirements"])

        # 1. Add new requirement
        add_resp = test_client.post(
            f"/api/projects/{project_id}/requirements",
            json={
                "title": "Custom Safety Gate Check",
                "statement": "The system shall enforce safety gate biometric checks.",
                "requirement_type": "security",
                "priority": "must",
                "rationale": "High-risk plant safety regulation",
                "acceptance_criteria": ["Biometric match validated before gate pass issue"],
            },
        )
        assert add_resp.status_code == 200
        updated_project = add_resp.json()
        assert len(updated_project["requirements"]) == initial_req_count + 1
        new_req = next(r for r in updated_project["requirements"] if r["title"] == "Custom Safety Gate Check")
        assert new_req["requirement_type"] == "security"
        assert new_req["priority"] == "must"
        assert new_req["review_status"] == "approved"

        # 2. Modify requirement
        mod_resp = test_client.patch(
            f"/api/requirements/{new_req['id']}",
            json={
                "title": "Custom Safety Gate Check (Updated)",
                "priority": "should",
                "statement": "The system shall enforce safety gate biometric checks for external contractors.",
            },
        )
        assert mod_resp.status_code == 200
        mod_project = mod_resp.json()
        mod_req = next(r for r in mod_project["requirements"] if r["id"] == new_req["id"])
        assert mod_req["title"] == "Custom Safety Gate Check (Updated)"
        assert mod_req["priority"] == "should"
        assert "contractors" in mod_req["statement"]

        # 3. Delete requirement
        del_resp = test_client.delete(f"/api/requirements/{new_req['id']}")
        assert del_resp.status_code == 200
        del_project = del_resp.json()
        assert len(del_project["requirements"]) == initial_req_count
        assert not any(r["id"] == new_req["id"] for r in del_project["requirements"])

