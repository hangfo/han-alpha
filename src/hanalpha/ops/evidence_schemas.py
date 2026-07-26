from __future__ import annotations

from datetime import datetime
from typing import Any

from hanalpha.ops.artifact_registry_types import ArtifactType

STRICT_DOCUMENT_TYPES = frozenset(
    {
        ArtifactType.LICENSE_RECEIPT,
        ArtifactType.ENTITLEMENT_PROBE,
        ArtifactType.REVIEW_APPROVAL,
        ArtifactType.RAW_SAMPLE_MANIFEST,
        ArtifactType.TIMESTAMP_AUDIT,
        ArtifactType.REVISION_AUDIT,
        ArtifactType.SYMBOLOGY_AUDIT,
        ArtifactType.SURVIVORSHIP_AUDIT,
    }
)

SCHEMA_PREFIXES: dict[ArtifactType, str] = {
    ArtifactType.LICENSE_RECEIPT: "pit-license-receipt-",
    ArtifactType.ENTITLEMENT_PROBE: "pit-entitlement-probe-",
    ArtifactType.REVIEW_APPROVAL: "qualification-review-receipt-",
    ArtifactType.RAW_SAMPLE_MANIFEST: "pit-raw-sample-manifest-",
    ArtifactType.TIMESTAMP_AUDIT: "pit-timestamp-audit-",
    ArtifactType.REVISION_AUDIT: "pit-revision-audit-",
    ArtifactType.SYMBOLOGY_AUDIT: "pit-symbology-audit-",
    ArtifactType.SURVIVORSHIP_AUDIT: "pit-survivorship-audit-",
}


def strict_document_valid(document: dict[str, Any], artifact_type: ArtifactType) -> bool:
    if artifact_type not in STRICT_DOCUMENT_TYPES:
        return True
    if document.get("artifact_type") != artifact_type.value:
        return False
    if not str(document.get("schema_version", "")).startswith(SCHEMA_PREFIXES[artifact_type]):
        return False
    if artifact_type is ArtifactType.REVIEW_APPROVAL:
        required = {
            "decision",
            "evidence_artifact_ids",
            "reviewer_id",
            "public_key_id",
            "reviewed_at",
            "expires_at",
            "signature",
        }
        return (
            required <= document.keys()
            and document["decision"] == "APPROVE"
            and _aware_period(document["reviewed_at"], document["expires_at"])
        )
    if artifact_type is ArtifactType.RAW_SAMPLE_MANIFEST:
        return (
            document.get("decision") == "PASS"
            and document.get("bounded") is True
            and document.get("secrets_redacted") is True
            and isinstance(document.get("responses"), list)
            and bool(document["responses"])
        )
    return (
        document.get("decision") in {"PASS", "BLOCKED", "APPROVED", "VERIFIED"}
        and isinstance(document.get("qualifies_checks"), list)
        and all(isinstance(item, str) and item for item in document["qualifies_checks"])
        and _aware_period(document.get("effective_from"), document.get("expires_at"))
    )


def _aware_period(start: object, end: object) -> bool:
    try:
        parsed_start = datetime.fromisoformat(str(start))
        parsed_end = datetime.fromisoformat(str(end))
    except ValueError:
        return False
    return (
        parsed_start.tzinfo is not None
        and parsed_end.tzinfo is not None
        and parsed_end > parsed_start
    )
