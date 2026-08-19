from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Postgres
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_db: str = "research_assistant"
    postgres_user: str = "ra_user"
    postgres_password: str = "changeme"

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    # Embedding
    embedding_provider: str = "local"  # "local" | "openai"
    openai_api_key: str = ""

    # LLM
    llm_provider: str = "openai"  # "openai" | "anthropic"
    llm_model: str = "gpt-4o-mini"
    anthropic_api_key: str = ""

    # arXiv
    arxiv_request_delay_seconds: float = 3.0

    # RAG
    retrieval_top_k: int = 6
    max_query_retries: int = 2

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    # MCP
    mcp_host: str = "0.0.0.0"
    mcp_port: int = 8001


settings = Settings()
