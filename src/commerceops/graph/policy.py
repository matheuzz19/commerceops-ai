from pydantic import BaseModel


class PolicyDecision(BaseModel):
    allowed: bool
    requires_confirmation: bool
    reason: str
    violations: list[str]
