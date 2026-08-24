from pydantic import BaseModel


class KillSwitchStatus(BaseModel):
    enabled: bool
    reason: str | None = None


class KillSwitchUpdate(BaseModel):
    enabled: bool
    reason: str | None = None


class OpsMetrics(BaseModel):
    migrations: int
    audit_events: int
    open_escalations: int
    pushed_records: int
    failed_pushes: int
    kill_switch_enabled: bool
