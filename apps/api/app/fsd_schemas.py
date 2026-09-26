from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SourceReference(StrictModel):
    requirement_id: str
    source_locator: str
    source_quote: str


class DocumentInfo(StrictModel):
    process_identifier: str
    classification: str
    application: str
    functional_area: str
    prepared_by: str


class Revision(StrictModel):
    version: str
    date: str
    author: str
    description: str


class SignOff(StrictModel):
    role: str
    name: str
    status: str


class Scope(StrictModel):
    business_context: str
    as_is_process: list[str]
    current_constraints: list[str]
    objectives: list[str]
    in_scope: list[str]
    out_of_scope: list[str]
    glossary: list[str]


class Actor(StrictModel):
    name: str
    actor_type: str
    responsibility: str
    requirement_ids: list[str]


class ProcessStep(StrictModel):
    step_id: str
    actor: str
    activity: str
    system_behavior: str
    decision_or_rule: str
    step_type: str = Field(default="task", description='Diagram shape: "start", "task", "decision" or "end"')
    branch_yes_label: str = Field(default="", description='Outcome wording for the positive branch of a decision, e.g. "Approved". Empty string for a task')
    branch_yes_target: str = Field(default="", description="step_id reached when the decision passes. Empty string to continue with the next step")
    branch_no_label: str = Field(default="", description='Outcome wording for the negative branch, e.g. "Rejected". Empty string for a task')
    branch_no_target: str = Field(default="", description="step_id reached when the decision fails, or a BRD-worded terminal outcome. Empty string for a task")
    outcome: str
    requirement_ids: list[str]


class ImprovementMapping(StrictModel):
    constraint: str
    to_be_response: str
    expected_improvement: str
    requirement_ids: list[str]


class ProcessFlowVariant(StrictModel):
    flow_type: str
    trigger: str
    flow: str
    expected_outcome: str
    requirement_ids: list[str]


class FunctionalRequirement(StrictModel):
    requirement_id: str
    requirement_key: str = Field(description="Exact duplicate of requirement_id for UI compatibility")
    title: str
    priority: str
    actors: list[str]
    trigger: str
    preconditions: list[str]
    functional_behavior: str
    postconditions: list[str]
    acceptance_criteria: list[str]
    assumptions: list[str]
    source: SourceReference
    source_quote: str = Field(description="Exact duplicate of source.source_quote for UI compatibility")


class BusinessRule(StrictModel):
    rule_id: str
    description: str
    condition: str
    result: str
    requirement_ids: list[str]


class DataMapping(StrictModel):
    mapping_id: str
    business_field: str
    source_system: str
    source_entity: str
    source_field: str
    target_field: str
    transformation: str
    authorization: str
    requirement_ids: list[str]


class StatusDefinition(StrictModel):
    status_id: str
    domain: str
    source_system: str
    source_value: str
    displayed_value: str
    semantic_state: str
    requirement_ids: list[str]


class MessageDefinition(StrictModel):
    message_id: str
    scenario: str
    message_type: str
    message_text: str
    user_action: str
    requirement_ids: list[str]


class NonFunctionalRequirement(StrictModel):
    nfr_id: str
    category: str
    requirement: str
    target: str
    measurement: str
    requirement_ids: list[str]


class ScreenField(StrictModel):
    field_id: str
    label: str
    control: str
    data_type: str
    required: str
    editable: str
    source_or_default: str
    validation: str
    value_help: str
    requirement_ids: list[str]


class ScreenAction(StrictModel):
    action: str
    enabled_when: str
    processing: str
    success_result: str
    failure_result: str
    authorization: str
    requirement_ids: list[str]


class ScreenMessage(StrictModel):
    message_id: str
    message_type: str
    trigger: str
    message_text: str
    user_action: str
    requirement_ids: list[str]


class ScreenSpecification(StrictModel):
    screen_id: str
    name: str
    purpose: str
    roles: list[str]
    entry_point: str
    exit_conditions: list[str]
    proposed_technology: str
    floorplan: str = Field(default="", description="list_report, object_page, my_inbox, scan, or form")
    navigates_to: list[str] = Field(default_factory=list)
    requirement_ids: list[str]
    ascii_wireframe: str
    fields: list[ScreenField]
    actions: list[ScreenAction]
    messages: list[ScreenMessage]


class ConfigurationItem(StrictModel):
    config_id: str
    item: str
    purpose: str
    proposed_value: str
    owner: str
    status: str
    requirement_ids: list[str]


class TechnicalObject(StrictModel):
    object_id: str
    name: str
    description: str
    object_type: str
    standard_custom_or_tbd: str
    trigger: str
    validations: list[str]
    requirement_ids: list[str]


class Interface(StrictModel):
    interface_id: str
    source: str
    target: str
    purpose: str
    direction: str
    protocol_or_format: str
    frequency: str
    authentication: str
    error_and_retry: str
    requirement_ids: list[str]


class RoleAuthorization(StrictModel):
    role_id: str
    business_role: str
    activities: list[str]
    data_scope: str
    transaction_or_app: str
    authorization_object: str
    sod_concern: str
    requirement_ids: list[str]


class TestCondition(StrictModel):
    test_id: str
    requirement_ids: list[str]
    scenario: str
    preconditions: list[str]
    steps: list[str]
    expected_result: str
    test_type: str


class TraceabilityRow(StrictModel):
    requirement_id: str
    brd_source: str
    process_step_ids: list[str]
    screen_ids: list[str]
    rule_ids: list[str]
    interface_or_object_ids: list[str]
    test_ids: list[str]
    coverage_status: str


class Risk(StrictModel):
    risk_id: str
    risk: str
    impact: str
    likelihood: str
    severity: str
    mitigation: str
    owner: str
    requirement_ids: list[str]


class OpenIssue(StrictModel):
    issue_id: str
    description: str
    decision_required: str
    proposed_owner: str
    priority: str
    status: str


class ReviewCheck(StrictModel):
    check: str
    result: str
    notes: str


class FSDDocument(StrictModel):
    title: str
    version: str
    status: str
    document_information: DocumentInfo
    revision_history: list[Revision]
    sign_offs: list[SignOff]
    relevant_documents: list[str]
    purpose: str
    scope: Scope
    functional_areas: list[str]
    actors_and_systems: list[Actor]
    as_is_narrative: str
    as_is_process_steps: list[ProcessStep]
    future_state_narrative: str
    improvement_mapping: list[ImprovementMapping]
    process_steps: list[ProcessStep]
    process_flow_mermaid: str = Field(description="Valid Mermaid flowchart with swimlane subgraphs, decisions and exception routes")
    alternate_and_exception_flows: list[str]
    process_flow_variants: list[ProcessFlowVariant]
    requirements: list[FunctionalRequirement]
    processing_logic: list[str]
    business_rules: list[BusinessRule]
    data_mappings: list[DataMapping]
    status_definitions: list[StatusDefinition]
    message_catalog: list[MessageDefinition]
    non_functional_requirements: list[NonFunctionalRequirement]
    screen_navigation_mermaid: str = Field(description="Valid Mermaid flowchart showing screen navigation and alternate outcomes")
    screens: list[ScreenSpecification]
    reports_and_notifications: list[str]
    configuration_items: list[ConfigurationItem]
    technical_objects: list[TechnicalObject]
    cross_process_impacts: list[str]
    batch_jobs: list[str]
    dependencies: list[str]
    interfaces: list[Interface]
    integration_sequence_mermaid: str = Field(description="Valid Mermaid sequenceDiagram or an explicit Not applicable statement")
    assumptions: list[str]
    roles_and_authorizations: list[RoleAuthorization]
    test_conditions: list[TestCondition]
    traceability: list[TraceabilityRow]
    ricefw_inventory: list[str]
    risks: list[Risk]
    outstanding_issues: list[OpenIssue]
    localization_requirements: list[str]
    controls: list[str]
    open_questions: list[str]
    review_checklist: list[ReviewCheck]


class FSDDesignDraft(StrictModel):
    """Compact model-owned design decisions; baseline-heavy rows are local."""

    document_information: DocumentInfo
    scope: Scope
    functional_areas: list[str] = Field(max_length=10)
    actors_and_systems: list[Actor] = Field(max_length=12)
    as_is_narrative: str
    future_state_narrative: str
    improvement_mapping: list[ImprovementMapping] = Field(max_length=10)
    process_steps: list[ProcessStep] = Field(min_length=1, max_length=12)
    process_flow_mermaid: str
    alternate_and_exception_flows: list[str] = Field(max_length=10)
    process_flow_variants: list[ProcessFlowVariant] = Field(max_length=8)
    processing_logic: list[str] = Field(max_length=16)
    business_rules: list[BusinessRule] = Field(min_length=1, max_length=20)
    data_mappings: list[DataMapping] = Field(max_length=40)
    status_definitions: list[StatusDefinition] = Field(max_length=40)
    message_catalog: list[MessageDefinition] = Field(max_length=30)
    non_functional_requirements: list[NonFunctionalRequirement] = Field(max_length=30)
    screen_navigation_mermaid: str
    screens: list[ScreenSpecification] = Field(min_length=1, max_length=10)
    reports_and_notifications: list[str] = Field(max_length=12)
    configuration_items: list[ConfigurationItem] = Field(max_length=12)
    technical_objects: list[TechnicalObject] = Field(max_length=12)
    cross_process_impacts: list[str] = Field(max_length=10)
    batch_jobs: list[str] = Field(max_length=10)
    dependencies: list[str] = Field(max_length=12)
    interfaces: list[Interface] = Field(max_length=10)
    integration_sequence_mermaid: str
    assumptions: list[str] = Field(max_length=12)
    roles_and_authorizations: list[RoleAuthorization] = Field(max_length=12)
    ricefw_inventory: list[str] = Field(max_length=15)
    risks: list[Risk] = Field(max_length=10)
    outstanding_issues: list[OpenIssue] = Field(max_length=12)
    localization_requirements: list[str] = Field(max_length=10)
    controls: list[str] = Field(max_length=12)
    open_questions: list[str] = Field(max_length=12)
