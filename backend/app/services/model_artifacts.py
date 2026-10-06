"""Keeps the ``model_artifacts`` table in step with the on-disk E1 artifact.

SH.docx §10.2 step 8 has the Colab notebook register each new version via the
API. Until that exists, the backend registers the bundled v1 artifact itself
so `GET /model/status` and the admin UI have a row to read.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.logging import get_logger
from app.models import ModelArtifact

logger = get_logger(__name__)

MODEL_NAME = "misplacement_classifier"


def _parse_timestamp(raw: Optional[str]) -> Optional[datetime]:
    if not raw:
        return None
    try:
        # Stored UTC-naive to match every other datetime in the schema.
        return datetime.fromisoformat(raw).replace(tzinfo=None)
    except ValueError:
        return None


def sync_local_artifact(db: Session) -> Optional[ModelArtifact]:
    """Registers the bundled artifact and makes it the only active row.

    Idempotent: safe to call on every startup.
    """
    artifact_dir: Path = settings.e1_artifact_path
    metadata_path = artifact_dir / "training_metadata.json"

    if not metadata_path.exists():
        logger.warning("No E1 training metadata at %s; skipping registration", metadata_path)
        return None

    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("E1 training metadata is not valid JSON; skipping registration")
        return None

    version = metadata.get("version", settings.e1_model_version)

    artifact = db.scalar(
        select(ModelArtifact).where(
            ModelArtifact.name == MODEL_NAME, ModelArtifact.version == version
        )
    )
    if artifact is None:
        artifact = ModelArtifact(name=MODEL_NAME, version=version)
        db.add(artifact)

    artifact.storage_path = str(artifact_dir)
    artifact.trained_at = _parse_timestamp(metadata.get("training_timestamp"))
    artifact.metrics_json = json.dumps(metadata.get("metrics", {}))
    artifact.is_active = True

    # SQLite has no partial unique index, so the "one active per name"
    # invariant is enforced here rather than by a constraint.
    others = db.scalars(
        select(ModelArtifact).where(
            ModelArtifact.name == MODEL_NAME, ModelArtifact.version != version
        )
    ).all()
    for other in others:
        other.is_active = False

    db.commit()
    logger.info("Registered E1 artifact %s %s as active", MODEL_NAME, version)
    return artifact


def get_active_artifact(db: Session, name: str = MODEL_NAME) -> Optional[ModelArtifact]:
    """Returns the active artifact row for ``name``, if any."""
    return db.scalar(
        select(ModelArtifact).where(
            ModelArtifact.name == name, ModelArtifact.is_active.is_(True)
        )
    )
