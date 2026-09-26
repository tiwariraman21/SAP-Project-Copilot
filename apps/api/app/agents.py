AGENT_CAPABILITIES = {
    "fsd": {"agent": "fsd_content", "validator": "fsd_release_gate", "template": "fsd-v1",
            "label": "Functional Specification", "depends_on": ["approved_requirements"]},
    "backlog": {"agent": "project_management", "label": "Backlog & Sprint Plan", "depends_on": ["approved_requirements"]},
    "technical_design": {"agent": "technical", "label": "Technical Design", "depends_on": ["approved_requirements", "fsd"]},
    "test_cases": {"agent": "quality", "label": "Test Cases", "depends_on": ["approved_requirements", "fsd"]},
    "traceability": {"agent": "governance", "label": "Traceability Matrix", "depends_on": ["approved_requirements"]},
    "companion": {"agent": "companion", "label": "AI Companion", "depends_on": ["project_knowledge"]},
}
