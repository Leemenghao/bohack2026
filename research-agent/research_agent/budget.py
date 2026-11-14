"""Cloud-call budget for one research run.

The track asks the agent to decide *when* to spend a cloud call given the task
difficulty, the feedback so far and the remaining budget. This module holds that
budget as plain data so the decision rules stay testable without a model.

Nothing here talks to a network or a model; `research_agent` wires it into the
prompt and the model-call limit.
"""

from dataclasses import dataclass, field


@dataclass
class Budget:
    """Hard limits for one run. `tokens` of 0 means "no token cap"."""

    calls: int = 8
    tokens: int = 0
    used_calls: int = 0
    used_tokens: int = 0
    exhausted_at: str = ""
    _history: list = field(default_factory=list, repr=False)

    def __post_init__(self):
        if self.calls < 1:
            raise ValueError("calls must be >= 1")
        if self.tokens < 0:
            raise ValueError("tokens must be >= 0")

    # ---- state ----

    @property
    def remaining_calls(self) -> int:
        return max(0, self.calls - self.used_calls)

    @property
    def remaining_tokens(self) -> int:
        if not self.tokens:
            return -1  # unbounded
        return max(0, self.tokens - self.used_tokens)

    @property
    def exhausted(self) -> bool:
        if self.remaining_calls <= 0:
            return True
        return bool(self.tokens) and self.remaining_tokens <= 0

    # ---- spending ----

    def can_call(self) -> bool:
        return not self.exhausted

    def spend_call(self, reason: str = "") -> bool:
        """Record one cloud call. Returns False when the budget is already spent."""
        if not self.can_call():
            if not self.exhausted_at:
                self.exhausted_at = "call_limit"
            return False
        self.used_calls += 1
        self._history.append({"kind": "call", "reason": reason, "used_calls": self.used_calls})
        if self.exhausted and not self.exhausted_at:
            self.exhausted_at = "call_limit"
        return True

    def spend_tokens(self, count: int) -> None:
        if count <= 0:
            return
        self.used_tokens += count
        if self.tokens and self.used_tokens >= self.tokens and not self.exhausted_at:
            self.exhausted_at = "token_limit"

    # ---- reporting ----

    def prompt_line(self) -> str:
        """One sentence the model sees, so it can plan its spending."""
        token_part = (
            f"，token 预算 {self.tokens}"
            if self.tokens
            else "，token 不限"
        )
        return (
            f"本次运行最多 {self.calls} 次云端调用{token_part}；"
            "预算耗尽后必须用已有证据收尾，不得再要求新的云端调用。"
        )

    def snapshot(self) -> dict:
        return {
            "limit_calls": self.calls,
            "limit_tokens": self.tokens,
            "used_calls": self.used_calls,
            "used_tokens": self.used_tokens,
            "remaining_calls": self.remaining_calls,
            "remaining_tokens": self.remaining_tokens if self.tokens else None,
            "exhausted": self.exhausted,
            "exhausted_at": self.exhausted_at,
        }
