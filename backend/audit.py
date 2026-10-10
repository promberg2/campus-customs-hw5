"""Append-only audit trail stored as a JSON array in output/audit_trail.json."""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Any

from backend.config import AUDIT_TEXT_LIMIT, AUDIT_TRAIL_FILE
from backend.models import AuditEvent, utc_now


def clip(value: Any, limit: int = AUDIT_TEXT_LIMIT) -> Any:
    """Keep audit entries readable: long strings and nested payloads are shortened, never dropped."""
    if isinstance(value, str):
        return value if len(value) <= limit else value[:limit] + f"... [+{len(value) - limit} chars]"
    if isinstance(value, dict):
        return {k: clip(v, limit) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clip(v, limit) for v in value]
    return value


def write_json_atomic(path: Path, data: Any) -> None:
    """Write via a temp file and os.replace, retrying while Windows/OneDrive briefly locks the target."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    for attempt in range(40):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 39:
                raise
            time.sleep(0.05 * (1 + attempt % 5))


def usage_dict(usage: Any) -> dict[str, Any]:
    fields = ("requests", "tool_calls", "input_tokens", "output_tokens")
    out = {f: getattr(usage, f, 0) or 0 for f in fields}
    out["total_tokens"] = out["input_tokens"] + out["output_tokens"]
    return out


class AuditTrail:
    """Every event is appended; existing entries are never rewritten or removed."""

    def __init__(self, path: Path = AUDIT_TRAIL_FILE) -> None:
        self.path = path
        self.pending = path.with_name(path.stem + ".pending.jsonl")
        self._lock = asyncio.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[Any]:
        if not self.path.exists() or not self.path.read_text(encoding="utf-8").strip():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            pass
        backup = self.path.with_name(f"audit_trail.unreadable-{utc_now().replace(':', '')}.json")
        os.replace(self.path, backup)
        return [{"ts": utc_now(), "event": "error", "detail": {"message": f"Unreadable trail moved to {backup.name}"}}]

    def _append_sync(self, entry: dict[str, Any]) -> None:
        entries = self._load()
        held = self.pending.read_text(encoding="utf-8").splitlines() if self.pending.exists() else []
        entries.extend(json.loads(line) for line in held if line.strip())
        entries.append(entry)
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(entries, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
        # Windows/OneDrive can briefly lock the file while syncing or previewing it.
        for attempt in range(40):
            try:
                os.replace(tmp, self.path)
                break
            except PermissionError:
                if attempt == 39:
                    raise
                time.sleep(0.05 * (1 + attempt % 5))
        if held:
            self.pending.unlink(missing_ok=True)

    def _hold_sync(self, entry: dict[str, Any]) -> None:
        with self.pending.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    async def log(self, event: AuditEvent) -> None:
        entry = clip(event.model_dump(mode="json", exclude_none=True))
        async with self._lock:
            try:
                await asyncio.to_thread(self._append_sync, entry)
            except OSError:
                await asyncio.to_thread(self._hold_sync, entry)
