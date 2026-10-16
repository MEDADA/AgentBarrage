"""Explainable ordering of current work items for human attention."""

from dataclasses import dataclass
import time


@dataclass(frozen=True)
class AttentionDecision:
    work_key: tuple[str, str, str, str]
    priority: int
    label: str
    needs_action: bool
    confidence: str
    project: str
    summary: str
    updated_at: float


def describe(item):
    if item.health == "stale":
        return 5, "状态未确认", False, "unknown"
    if item.state == "waiting_approval" and item.attention_confidence == "confirmed":
        return 0, "需要批准", True, "confirmed"
    if item.state == "waiting_input" and item.attention_confidence == "confirmed":
        return 1, "需要输入", True, "confirmed"
    if item.state == "failed":
        return 2, "执行失败", True, "confirmed"
    if item.attention == "approval" and item.attention_confidence == "tentative":
        return 3, "可能需要批准", False, "tentative"
    if item.state == "blocked":
        return 4, "已阻塞", True, "confirmed"
    if item.state == "completed":
        return 6, "已完成", False, "confirmed"
    if item.state == "working":
        return 7, "正在工作", False, "confirmed"
    if item.state == "submitted":
        return 8, "已接收", False, "confirmed"
    return 9, "状态未确认", False, "unknown"


class AttentionEngine:
    def __init__(self, tentative_ttl=30):
        self.tentative_ttl = tentative_ttl

    def decide(self, items, *, private=False, paused=False, now=None):
        if private or paused:
            return []
        now = time.time() if now is None else now
        decisions = []
        for item in items:
            if (item.attention_confidence == "tentative"
                    and now - item.updated_at > self.tentative_ttl):
                priority, label, needs_action, confidence = 9, "状态未确认", False, "unknown"
            else:
                priority, label, needs_action, confidence = describe(item)
            decisions.append(AttentionDecision(
                item.key, priority, label, needs_action, confidence,
                item.project, item.summary, item.updated_at,
            ))
        return sorted(decisions, key=lambda item: (item.priority, item.updated_at, item.work_key))


def format_attention_rows(decisions, limit=20):
    """Readable list for the menu-bar task window, without raw source payloads."""
    if not decisions:
        return "暂无可确认的智能体任务"
    rows = []
    for decision in decisions[:limit]:
        agent = decision.work_key[0].upper()
        heading = f"{agent} · {decision.project}" if decision.project else agent
        detail = decision.label
        if decision.confidence != "tentative" and decision.summary:
            detail += f" · {decision.summary}"
        rows.append(f"{heading}\n{detail}")
    if len(decisions) > limit:
        rows.append(f"还有 {len(decisions) - limit} 项未显示")
    return "\n\n".join(rows)
