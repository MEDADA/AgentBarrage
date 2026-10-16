"""Pure, conservative lifecycle transitions for one identifiable work item."""

from dataclasses import dataclass, replace


TERMINAL = {"completed", "failed", "cancelled"}


@dataclass(frozen=True)
class WorkSnapshot:
    key: tuple[str, str, str, str]
    state: str = "unknown"
    health: str = "fresh"
    updated_at: float = 0.0
    last_event_id: str = ""
    last_sequence: int | None = None
    stop_observed: bool = False
    attention: str = ""
    attention_confidence: str = ""
    project: str = ""
    summary: str = ""


def reduce_work(previous: WorkSnapshot | None, event: dict, received_at: float,
                key: tuple[str, str, str, str]) -> WorkSnapshot:
    """Apply a canonical observation without inferring a whole-task outcome."""
    current = previous or WorkSnapshot(key=key)
    sequence = event.get("sequence")
    if current.state in TERMINAL:
        return replace(current, last_event_id=event["event_id"],
                       last_sequence=sequence if sequence is not None else current.last_sequence)

    state = current.state
    attention = current.attention
    confidence = current.attention_confidence
    stop_observed = current.stop_observed
    event_type = event["event_type"]

    if event_type == "prompt_submitted":
        state, attention, confidence, stop_observed = "submitted", "", "", False
    elif event_type in {"tool_started", "subagent_started"}:
        state = "working"
        if confidence == "tentative":
            attention, confidence = "", ""
    elif event_type in {"tool_finished", "tool_failed", "turn_stop_observed", "subagent_finished"}:
        if confidence == "tentative":
            attention, confidence = "", ""
        if event_type in {"turn_stop_observed", "subagent_finished"}:
            state = "unknown"
            stop_observed = event_type == "turn_stop_observed"
    elif event_type == "approval_requested":
        attention, confidence = "approval", "tentative"
    elif event_type == "approval_visible":
        state, attention, confidence = "waiting_approval", "approval", "confirmed"
    elif event_type == "input_requested":
        state, attention, confidence = "waiting_input", "input", "confirmed"
    elif event_type in {"turn_failed", "task_failed"}:
        state, attention, confidence = "failed", "", ""
    elif event_type in {"turn_interrupted", "task_cancelled"}:
        state, attention, confidence = "cancelled", "", ""
    elif event_type == "task_completed":
        state, attention, confidence = "completed", "", ""

    return replace(current, state=state, health="fresh", updated_at=received_at,
                   last_event_id=event["event_id"],
                   last_sequence=sequence if sequence is not None else current.last_sequence,
                   stop_observed=stop_observed, attention=attention,
                   attention_confidence=confidence,
                   project=event.get("project") or current.project,
                   summary=("本轮结束状态未确认" if event_type == "turn_stop_observed"
                            else event.get("summary") or current.summary))
