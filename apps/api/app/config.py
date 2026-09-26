from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "sqlite:///./sap_copilot.db"
    openai_api_key: str | None = None
    # Use a capable model once for deep BRD understanding, a lower-cost model
    # for repetitive requirement extraction, and a balanced model for FSD synthesis.
    openai_brd_model: str = "gpt-5.6-terra"
    openai_requirements_model: str = "gpt-5.6-luna"
    openai_fsd_model: str = "gpt-5.6-terra"
    openai_companion_model: str = "gpt-5.6-luna"
    openai_timeout_seconds: float = 180
    openai_brd_timeout_seconds: float = 240
    openai_brd_max_retries: int = 1
    openai_brd_max_output_tokens: int = 24000
    openai_brd_use_file_input: bool = True
    openai_brd_reasoning_effort: str = "low"
    openai_requirements_max_output_tokens: int = 12000
    openai_requirements_batch_characters: int = 12000
    openai_requirements_max_batches: int = 50
    openai_requirements_parallel_batches: int = 5
    openai_fsd_max_output_tokens: int = 24000
    openai_fsd_timeout_seconds: float = 120
    openai_fsd_max_retries: int = 1
    openai_max_source_characters: int = 500000
    openai_allow_demo_fallback: bool = False
    cors_origins: str = "http://localhost:3000"
    upload_dir: str = "uploads"
    artifact_dir: str = "generated"
    jira_url: str | None = None
    jira_email: str | None = None
    jira_api_token: str | None = None
    jira_project_key: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @property
    def origins(self) -> list[str]:
        return [value.strip() for value in self.cors_origins.split(",") if value.strip()]


def get_settings() -> Settings:
    return Settings(_env_file=".env")


settings = get_settings()

