"""Provider-neutral, approval-gated publishing boundary.

The core project intentionally ships with no real social-network publisher.
Adapters can register a platform-specific implementation later, while agents
and the dashboard can already preview the exact decision path safely.
"""

from __future__ import annotations

import os
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol
from uuid import UUID

from packages.contracts.models import (
    PublishAuditRecord,
    PublishSocialDraftResponse,
    SocialDraft,
    SocialPlatform,
)

from .approvals import ApprovalStore
from .audit import AuditStore

_SECRET_RE = re.compile(
    r"(?i)\b(authorization|api[_-]?key|token|password|secret)\b\s*[:=]\s*[^\s,;]+"
)


class PublishingError(RuntimeError):
    """Safe, user-facing publisher failure without raw provider payloads."""


class Publisher(Protocol):
    """The smallest contract a platform adapter must implement."""

    publisher_id: str
    platform: SocialPlatform

    async def publish(self, draft: SocialDraft, *, video_path: Path | None = None) -> str: ...


@dataclass(frozen=True, slots=True)
class PublisherDescriptor:
    publisher_id: str
    platform: SocialPlatform
    configured: bool = True


@dataclass(slots=True)
class PublisherRegistry:
    _publishers: dict[SocialPlatform, Publisher] = field(default_factory=dict)

    def register(self, publisher: Publisher) -> None:
        if not publisher.publisher_id.strip():
            raise ValueError("publisher_id must not be empty")
        self._publishers[publisher.platform] = publisher

    def get(self, platform: SocialPlatform) -> Publisher | None:
        return self._publishers.get(platform)

    def descriptors(self) -> list[PublisherDescriptor]:
        return [
            PublisherDescriptor(
                publisher_id=publisher.publisher_id,
                platform=publisher.platform,
                configured=True,
            )
            for publisher in self._publishers.values()
        ]

    def __iter__(self) -> Iterable[Publisher]:
        return iter(self._publishers.values())


def _safe_message(message: str) -> str:
    return _SECRET_RE.sub(r"\1=[REDACTED]", message.replace("\n", " "))[:500]


@dataclass(slots=True)
class PublishingService:
    """Apply dry-run and human approval policy before an adapter is called."""

    approvals: ApprovalStore
    audit: AuditStore
    publishers: PublisherRegistry = field(default_factory=PublisherRegistry)
    enabled: bool = False

    def _audit(
        self,
        *,
        job_id: UUID,
        platform: SocialPlatform,
        action: str,
        actor: str,
        dry_run: bool,
        message: str,
        external_id: str | None = None,
    ) -> PublishAuditRecord:
        event = PublishAuditRecord(
            job_id=job_id,
            platform=platform,
            action=action,  # type: ignore[arg-type] - model validates the public action
            actor=actor,
            dry_run=dry_run,
            message=_safe_message(message),
            external_id=external_id,
        )
        return self.audit.record(event)

    async def publish(
        self,
        *,
        job_id: UUID,
        draft: SocialDraft,
        actor: str = "agent",
        dry_run: bool = True,
        video_path: Path | None = None,
    ) -> PublishSocialDraftResponse:
        latest = self.approvals.latest(job_id).get(draft.platform)
        approved = latest is not None and latest.decision == "approved"

        if dry_run:
            audit = self._audit(
                job_id=job_id,
                platform=draft.platform,
                action="publish_dry_run",
                actor=actor,
                dry_run=True,
                message="dry-run only; no external publisher was called",
            )
            return PublishSocialDraftResponse(
                job_id=job_id,
                platform=draft.platform,
                status="dry_run",
                dry_run=True,
                approved=approved,
                publisher_id=(
                    self.publishers.get(draft.platform).publisher_id
                    if self.publishers.get(draft.platform)
                    else None
                ),
                audit_id=audit.audit_id,
                message="preview generated; no external side effect",
            )

        if not approved:
            audit = self._audit(
                job_id=job_id,
                platform=draft.platform,
                action="publish_blocked",
                actor=actor,
                dry_run=False,
                message="human approval is required before external publishing",
            )
            return PublishSocialDraftResponse(
                job_id=job_id,
                platform=draft.platform,
                status="blocked",
                dry_run=False,
                approved=False,
                audit_id=audit.audit_id,
                message="human approval is required before external publishing",
            )

        publisher = self.publishers.get(draft.platform)
        if not self.enabled:
            audit = self._audit(
                job_id=job_id,
                platform=draft.platform,
                action="publish_unavailable",
                actor=actor,
                dry_run=False,
                message="external publishing is disabled by service policy",
            )
            return PublishSocialDraftResponse(
                job_id=job_id,
                platform=draft.platform,
                status="unavailable",
                dry_run=False,
                approved=True,
                publisher_id=publisher.publisher_id if publisher else None,
                audit_id=audit.audit_id,
                message="external publishing is disabled by service policy",
            )

        if publisher is None:
            audit = self._audit(
                job_id=job_id,
                platform=draft.platform,
                action="publish_unavailable",
                actor=actor,
                dry_run=False,
                message="no publisher adapter is configured for this platform",
            )
            return PublishSocialDraftResponse(
                job_id=job_id,
                platform=draft.platform,
                status="unavailable",
                dry_run=False,
                approved=True,
                audit_id=audit.audit_id,
                message="no publisher adapter is configured for this platform",
            )

        try:
            external_id = await publisher.publish(draft, video_path=video_path)
        except Exception as exc:  # noqa: BLE001 - provider boundary must not leak failures
            message = _safe_message(str(exc)) or "publisher adapter failed"
            audit = self._audit(
                job_id=job_id,
                platform=draft.platform,
                action="publish_failed",
                actor=actor,
                dry_run=False,
                message=message,
                external_id=None,
            )
            return PublishSocialDraftResponse(
                job_id=job_id,
                platform=draft.platform,
                status="failed",
                dry_run=False,
                approved=True,
                publisher_id=publisher.publisher_id,
                audit_id=audit.audit_id,
                message=message,
            )

        audit = self._audit(
            job_id=job_id,
            platform=draft.platform,
            action="publish_succeeded",
            actor=actor,
            dry_run=False,
            message="publisher accepted the draft",
            external_id=external_id,
        )
        return PublishSocialDraftResponse(
            job_id=job_id,
            platform=draft.platform,
            status="published",
            dry_run=False,
            approved=True,
            publisher_id=publisher.publisher_id,
            external_id=external_id,
            audit_id=audit.audit_id,
            message="publisher accepted the draft",
        )


def external_publishing_enabled() -> bool:
    """Read the explicit server-side opt-in for non-dry-run publishing."""

    return os.getenv("AIVS_EXTERNAL_PUBLISH_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
