from types import SimpleNamespace

from app.services.project_identity import business_project_name, looks_like_person_name, priority_label, process_identifier


def test_person_name_is_not_used_when_brd_has_process_title():
    chunk = SimpleNamespace(text="Business Requirements Document for Purchase Requisition Approval in SAP S/4HANA.")
    document = SimpleNamespace(filename="Anurag_Umale.docx", chunks=[chunk])
    project = SimpleNamespace(
        name="Anurag Umale",
        document=document,
        requirements=[SimpleNamespace(title="Create purchase requisition", statement="The requester must create a purchase requisition.")],
        brd_knowledge=None,
    )

    assert looks_like_person_name("Anurag Umale")
    assert business_project_name(project) == "Purchase Requisition Approval"
    assert process_identifier(project) == "PURCHASE-REQUISITION-APPROVAL"
    assert "Anurag" not in process_identifier(project)


def test_filename_supplies_project_name_when_typed_name_is_a_person():
    document = SimpleNamespace(filename="SAP_Purchase_Requisition_Approval_BRD.pdf", chunks=[])
    project = SimpleNamespace(name="Anurag Umale", document=document, requirements=[], brd_knowledge=None)

    assert business_project_name(project) == "SAP Purchase Requisition Approval"


def test_priority_labels_are_human_readable():
    assert priority_label("must") == "Must Have"
    assert priority_label("should") == "Good To Have"
    assert priority_label("could") == "Nice To Have"
    assert priority_label("won't") == "Won't Have"
    assert priority_label("Must") == "Must Have"
