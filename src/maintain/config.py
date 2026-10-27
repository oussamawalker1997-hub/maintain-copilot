import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: Path
    requests_per_minute: int = 60
    max_body_bytes: int = 28_000_000
    backend: str = "sqlite"
    postgres_secrets: Path = Path(".local/postgres")
    postgres_port: int = 15432

    def __post_init__(self):
        if self.backend not in ("sqlite", "postgres"):
            raise ValueError("MAINTAIN_BACKEND must be sqlite or postgres")
        if not 1 <= self.postgres_port <= 65535:
            raise ValueError("Invalid PostgreSQL port")

    @classmethod
    def from_env(cls):
        return cls(
            database=Path(os.getenv("MAINTAIN_DATABASE", ".local/maintain.sqlite")),
            backend=os.getenv("MAINTAIN_BACKEND", "sqlite"),
            postgres_secrets=Path(os.getenv("MAINTAIN_PG_SECRETS", ".local/postgres")),
            postgres_port=int(os.getenv("MAINTAIN_PG_PORT", "15432")),
        )
