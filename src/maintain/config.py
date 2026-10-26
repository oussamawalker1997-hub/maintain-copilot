import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database: Path
    requests_per_minute: int = 60
    max_body_bytes: int = 28_000_000

    @classmethod
    def from_env(cls):
        return cls(database=Path(os.getenv("MAINTAIN_DATABASE", ".local/maintain.sqlite")))
