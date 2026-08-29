from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "Internal Docs"
    org_name: str = ""
    public_origin: str = "http://127.0.0.1:8765"
    secret_key: str = ""
    cors_origins: str = "http://127.0.0.1:8765,http://localhost:8765"

    ollama_host: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.2"
    embedding_model: str = "hash"
    rerank_enabled: bool = False
    rerank_model: str = "BAAI/bge-reranker-base"
    top_k: int = 6
    retrieve_k: int = 20
    rrf_k: int = 60
    max_chunks_per_source: int = 2
    chunk_size: int = 800
    chunk_overlap: int = 120

    data_dir: Path = ROOT_DIR / "data"
    docs_dir: Path = ROOT_DIR / "data" / "docs"
    chroma_dir: Path = ROOT_DIR / "data" / "chroma"
    bm25_dir: Path = ROOT_DIR / "data" / "bm25"

    collection_name: str = "internal_docs"
    query_prefix: str = "Represent this sentence for searching relevant passages: "

    oidc_issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = ""
    oidc_redirect_path: str = "/api/auth/oidc/callback"

    @property
    def cors_origin_list(self) -> list[str]:
        return [part.strip() for part in self.cors_origins.split(",") if part.strip()]

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def spaces_dir(self) -> Path:
        return self.data_dir / "spaces"

    def space_root(self, space_id: str) -> Path:
        return self.spaces_dir / space_id


settings = Settings()
