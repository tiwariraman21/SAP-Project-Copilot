from pydantic import BaseModel, ConfigDict, Field


class StrictBRDModel(BaseModel):
    """Strict structured-output base model used for BRD understanding."""

    model_config = ConfigDict(extra="forbid")


class BRDEvidence(StrictBRDModel):
    page: int = Field(ge=0, description="1-based source page when known, otherwise 0")
    section: str
    quote: str


class BRDDocumentControl(StrictBRDModel):
    document_name: str
    document_type: str
    version: str
    status: str
    prepared_date: str
    business_area: str
    primary_business_system: str
    operational_master_data_system: str
    user_experience: str
    primary_integration_pattern: str


class BRDStakeholder(StrictBRDModel):
    name: str
    primary_need: str
    expected_access: str
    evidence: BRDEvidence


class BRDProcessStep(StrictBRDModel):
    step_id: str
    activity: str
    actor: str
    system: str
    business_result: str
    evidence: BRDEvidence


class BRDBusinessRequirement(StrictBRDModel):
    requirement_id: str
    area: str
    requirement: str
    priority: str
    evidence: BRDEvidence


class BRDDataField(StrictBRDModel):
    field_name: str
    source_system: str
    source_entity_or_domain: str
    display_requirement: str
    sensitivity_or_authorization: str
    evidence: BRDEvidence


class BRDStatusDefinition(StrictBRDModel):
    domain: str
    allowed_values: list[str]
    evidence: BRDEvidence


class BRDScreen(StrictBRDModel):
    screen_id: str
    name: str
    floorplan: str
    purpose: str
    roles: list[str]
    fields: list[str]
    filters: list[str]
    columns: list[str]
    actions: list[str]
    navigation: list[str]
    business_rules: list[str]
    evidence: BRDEvidence


class BRDIntegration(StrictBRDModel):
    integration_id: str
    source: str
    target: str
    purpose: str
    protocol_or_pattern: str
    identifiers_or_payload: str
    error_or_freshness_rule: str
    evidence: BRDEvidence


class BRDBusinessRule(StrictBRDModel):
    rule_id: str
    rule: str
    evidence: BRDEvidence


class BRDMessage(StrictBRDModel):
    scenario: str
    message: str
    expected_behavior: str
    evidence: BRDEvidence


class BRDNonFunctionalRequirement(StrictBRDModel):
    category: str
    requirement: str
    target_or_principle: str
    evidence: BRDEvidence


class BRDRisk(StrictBRDModel):
    risk: str
    impact: str
    mitigation: str
    evidence: BRDEvidence


class BRDAcceptanceCriterion(StrictBRDModel):
    criterion_id: str
    criterion: str
    evidence: BRDEvidence


class BRDTestScenario(StrictBRDModel):
    test_id: str
    scenario: str
    expected_result: str
    evidence: BRDEvidence


class BRDKnowledgeBase(StrictBRDModel):
    """Project facts extracted once from the BRD and reused by later agents."""

    document_control: BRDDocumentControl
    executive_summary: str
    business_context: str
    objectives: list[str]
    business_drivers: list[str]
    success_measures: list[str]
    current_state_challenges: list[str]
    desired_future_state: str
    in_scope: list[str]
    out_of_scope: list[str]
    stakeholders: list[BRDStakeholder]
    role_principles: list[str]
    process_steps: list[BRDProcessStep]
    data_ownership_rules: list[str]
    business_requirements: list[BRDBusinessRequirement]
    data_fields: list[BRDDataField]
    status_definitions: list[BRDStatusDefinition]
    screens: list[BRDScreen]
    integrations: list[BRDIntegration]
    business_rules: list[BRDBusinessRule]
    messages: list[BRDMessage]
    non_functional_requirements: list[BRDNonFunctionalRequirement]
    assumptions: list[str]
    dependencies: list[str]
    risks: list[BRDRisk]
    acceptance_criteria: list[BRDAcceptanceCriterion]
    business_test_scenarios: list[BRDTestScenario]
    glossary: list[str]
    references: list[str]
    open_questions: list[str]
    coverage_notes: list[str]
