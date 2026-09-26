# Example Input for the SAP FSD Model Template

Provide this structure after the model instruction in `SAP_FSD_MODEL_TEMPLATE.md`.

```text
PROJECT_METADATA
- Project name: S/4HANA Order-to-Cash Improvement
- Process identifier: SAP/OTC/001
- Functional area/module: TBD
- Application/landscape: TBD
- Classification: Internal
- Prepared by: Functional Design Team
- Reviewers: TBD
- Approvers: TBD
- Target version/date: 0.1 / DD-MMM-YYYY

BRD_CONTENT
[Page 1, paragraph 1]
The system must validate that the customer master record is active before a sales order can be saved.

[Page 1, paragraph 2]
The system shall verify the customer's available credit before releasing a sales order for fulfillment.

[Page 1, paragraph 3]
If the order exceeds the available credit limit, the system must place the sales order on credit hold and notify the assigned credit manager.

APPROVED_REQUIREMENTS
- Requirement ID: REQ-001
  Title: Validate active customer
  Statement: The system must validate that the customer master record is active before a sales order can be saved.
  Priority: Must
  Acceptance criteria:
    - Given an inactive customer, when a user attempts to save a sales order, then saving is prevented and an actionable validation message is displayed.
  Source: Page 1, paragraph 1
  Source quote: "The system must validate that the customer master record is active before a sales order can be saved."

- Requirement ID: REQ-002
  Title: Validate available credit
  Statement: The system shall verify available customer credit before order release.
  Priority: Must
  Acceptance criteria:
    - Given insufficient available credit, when release is attempted, then the order is placed on credit hold.
  Source: Page 1, paragraphs 2-3
  Source quote: "If the order exceeds the available credit limit, the system must place the sales order on credit hold."

OPTIONAL_CONTEXT
- No confirmed Fiori app ID, transaction code, SAP table, integration middleware, or authorization object is available. These must remain TBD.
```

Expected behavior: the generated FSD should propose grounded process and screen structures, preserve `REQ-001` and `REQ-002`, include validation and credit-hold exception paths, and list unresolved SAP implementation details as open issues instead of inventing them.
