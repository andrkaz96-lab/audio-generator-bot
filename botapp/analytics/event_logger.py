from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EventLogger:
    api_key: str
    host: str = "https://app.posthog.com"
    timeout_seconds: float = 2.0
    enabled: bool = True

    async def capture(
        self,
        *,
        event: str,
        distinct_id: str,
        properties: dict[str, Any] | None = None,
    ) -> None:
        if not self.enabled or not self.api_key:
            return

        safe_properties = dict(properties or {})
        safe_properties["platform"] = "telegram"
        safe_properties["$lib"] = "audio-generator-bot"
        safe_properties["event_sent_at"] = datetime.now(timezone.utc).isoformat()

        payload = {
            "api_key": self.api_key,
            "event": event,
            "distinct_id": distinct_id,
            "properties": safe_properties,
        }

        endpoint = f"{self.host.rstrip('/')}/capture/"
        try:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(endpoint, json=payload)
                response.raise_for_status()
        except Exception:
            logger.exception("Failed to send analytics event '%s'", event)
