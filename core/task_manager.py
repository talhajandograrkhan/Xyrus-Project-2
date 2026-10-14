from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from memory.memory_manager import add_task, complete_task, list_tasks, load_memory, save_memory

RiskLevel = Literal["low", "medium", "high"]
TaskStatus = Literal["pending", "in_progress", "completed", "blocked", "needs_approval"]


class SafeTaskManager:
    """Lightweight, safe task manager for a personal assistant.

    This layer is intentionally conservative:
    - low-risk tasks can proceed automatically
    - medium/high-risk tasks require explicit approval before execution
    - tasks are persisted in the existing memory store so the assistant keeps
      track of what it promised to do
    - multi-step plans can checkpoint and resume later without losing state
    """

    def __init__(self) -> None:
        self._risk_order = {"low": 0, "medium": 1, "high": 2}

    def _task_store(self) -> tuple[dict[str, Any], dict[str, Any]]:
        memory = load_memory()
        tasks = memory.get("tasks", {})
        if not isinstance(tasks, dict):
            tasks = {}
        memory["tasks"] = tasks
        return memory, tasks

    def _slugify_task_key(self, title: str, used: set[str] | None = None) -> str:
        import re
        slug = re.sub(r"[^a-z0-9]+", "_", (title or "task").strip().lower()).strip("_") or "task"
        if used is None:
            used = set()
        base = slug
        counter = 2
        while slug in used:
            slug = f"{base}_{counter}"
            counter += 1
        used.add(slug)
        return slug

    def _persist_task(self, task_key: str, task: dict[str, Any]) -> dict[str, Any]:
        memory, tasks = self._task_store()
        tasks[task_key] = task
        memory["tasks"] = tasks
        save_memory(memory)
        return task

    def _load_task(self, task_key: str) -> dict[str, Any] | None:
        _, tasks = self._task_store()
        task = tasks.get(task_key)
        if not isinstance(task, dict):
            return None
        return task

    def _task_snapshot(self, task: dict[str, Any]) -> dict[str, Any]:
        snapshot = dict(task)
        if "plan_steps" in snapshot and not isinstance(snapshot["plan_steps"], list):
            snapshot["plan_steps"] = []
        if "action_history" not in snapshot:
            snapshot["action_history"] = []
        if "activity_timeline" not in snapshot:
            snapshot["activity_timeline"] = []
        if "checkpoints" not in snapshot:
            snapshot["checkpoints"] = []
        if "current_step" not in snapshot:
            snapshot["current_step"] = 0
        else:
            try:
                snapshot["current_step"] = int(snapshot["current_step"])
            except (TypeError, ValueError):
                snapshot["current_step"] = 0
        if "plan_status" not in snapshot:
            snapshot["plan_status"] = snapshot.get("status", "pending")
        return snapshot

    def create_plan(
        self,
        title: str,
        steps: list[str],
        description: str = "",
        risk_level: RiskLevel | str = "low",
        status: TaskStatus | str = "pending",
        approved_by_user: bool = False,
    ) -> dict[str, Any]:
        """Create a persisted, multi-step plan that can checkpoint and resume."""
        safe_title = (title or "").strip()
        if not safe_title:
            raise ValueError("Task title is required.")

        normalized_steps = []
        for step in steps or []:
            text = str(step or "").strip()
            if text:
                normalized_steps.append(text)
        if not normalized_steps:
            raise ValueError("At least one task step is required.")

        risk = self._normalize_risk(risk_level)
        task_status = self._normalize_status(status)
        if risk in {"medium", "high"} and not approved_by_user:
            task_status = "needs_approval"
        if task_status == "completed":
            task_status = "pending"

        _, tasks = self._task_store()
        task_key = self._slugify_task_key(safe_title, set(tasks.keys()))
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        plan = {
            "key": task_key,
            "title": safe_title,
            "description": description or "",
            "status": task_status,
            "plan_status": task_status,
            "risk_level": risk,
            "approved_by_user": approved_by_user,
            "plan_steps": normalized_steps,
            "current_step": 0,
            "checkpoints": [],
            "action_history": [],
            "activity_timeline": [],
            "created_at": now,
            "updated_at": now,
            "is_plan": True,
            "value": f"{task_status.upper()} | {description.strip() or 'No description'} | {safe_title}",
        }
        return self._persist_task(task_key, plan)

    def get_plan(self, task_key: str) -> dict[str, Any] | None:
        task = self._load_task(task_key)
        if task is None:
            return None
        return self._task_snapshot(task)

    def start_plan(self, task_key: str, note: str = "Plan started") -> dict[str, Any]:
        task = self.get_plan(task_key)
        if task is None:
            raise KeyError(f"Task '{task_key}' not found.")

        task["status"] = "in_progress"
        task["plan_status"] = "in_progress"
        task["current_step"] = max(0, min(task.get("current_step", 0), len(task.get("plan_steps", [])) - 1))
        task["action_history"] = list(task.get("action_history", []))
        task["action_history"].append({
            "action": "start",
            "note": note,
            "step_index": task["current_step"],
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        task["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._persist_task(task_key, task)

    def checkpoint(self, task_key: str, note: str = "Checkpoint", step_index: int | None = None) -> dict[str, Any]:
        task = self.get_plan(task_key)
        if task is None:
            raise KeyError(f"Task '{task_key}' not found.")

        steps = task.get("plan_steps", [])
        planned_index = task.get("current_step", 0)
        if step_index is not None:
            planned_index = max(0, min(int(step_index), max(0, len(steps) - 1)))
        task["current_step"] = planned_index
        task["status"] = "in_progress"
        task["plan_status"] = "in_progress"
        checkpoint = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "step_index": planned_index,
            "step": steps[planned_index] if planned_index < len(steps) else "",
            "note": note or "Checkpoint",
        }
        task.setdefault("checkpoints", []).append(checkpoint)
        task.setdefault("action_history", []).append({
            "action": "checkpoint",
            "note": note or "Checkpoint",
            "step_index": planned_index,
            "timestamp": checkpoint["timestamp"],
        })
        task["updated_at"] = checkpoint["timestamp"]
        return self._persist_task(task_key, task)

    def advance_plan(self, task_key: str, step_index: int | None = None, note: str = "Advanced") -> dict[str, Any]:
        task = self.get_plan(task_key)
        if task is None:
            raise KeyError(f"Task '{task_key}' not found.")

        steps = task.get("plan_steps", [])
        if not steps:
            raise ValueError("This plan has no steps.")

        current = task.get("current_step", 0)
        next_step = current if step_index is None else max(0, min(int(step_index), len(steps) - 1))
        if step_index is None:
            next_step = min(len(steps) - 1, current + 1)
        task["current_step"] = next_step
        if next_step >= len(steps) - 1:
            task["status"] = "completed"
            task["plan_status"] = "completed"
        else:
            task["status"] = "in_progress"
            task["plan_status"] = "in_progress"
        task.setdefault("action_history", []).append({
            "action": "advance",
            "note": note,
            "step_index": next_step,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        })
        task["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._persist_task(task_key, task)

    def resume_plan(self, task_key: str) -> dict[str, Any]:
        task = self.get_plan(task_key)
        if task is None:
            raise KeyError(f"Task '{task_key}' not found.")
        if task.get("plan_status") == "completed":
            task["status"] = "completed"
        elif task.get("status") not in {"in_progress", "blocked", "pending"}:
            task["status"] = "in_progress"
        task["plan_status"] = task["status"]
        task["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._persist_task(task_key, task)

    def record_activity(
        self,
        task_key: str,
        *,
        said: str = "",
        action: str = "",
        result: str = "",
        failed: bool = False,
        failure_reason: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        """Append an actionable timeline event describing the human input,
        the tool/action invoked, the result, and any failure details.

        The structure is intentionally compact and serializable so it can be
        persisted and later reviewed in the UI or memory panel.
        """
        task = self.get_plan(task_key)
        if task is None:
            raise KeyError(f"Task '{task_key}' not found.")

        entry = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "said": str(said or "").strip(),
            "action": str(action or "").strip(),
            "result": str(result or "").strip(),
            "failed": bool(failed),
            "failure_reason": str(failure_reason or "").strip(),
            "status": str(status or task.get("status") or "pending").strip(),
        }
        task.setdefault("activity_timeline", []).append(entry)
        task["updated_at"] = entry["timestamp"]
        return self._persist_task(task_key, task)

    def get_activity_timeline(self, task_key: str) -> list[dict[str, Any]]:
        task = self.get_plan(task_key)
        if task is None:
            raise KeyError(f"Task '{task_key}' not found.")
        return list(task.get("activity_timeline", []) or [])

    def clear_action_history(self, task_key: str) -> dict[str, Any]:
        task = self.get_plan(task_key)
        if task is None:
            raise KeyError(f"Task '{task_key}' not found.")
        task["action_history"] = []
        task["activity_timeline"] = []
        task["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return self._persist_task(task_key, task)

    def list_plans(self, limit: int = 10, include_completed: bool = True) -> list[dict[str, Any]]:
        rows = list_tasks(limit=max(1, limit))
        plans = []
        for item in rows:
            key = item.get("key")
            task = self.get_plan(key) if key else None
            if task is None:
                continue
            if not include_completed and str(task.get("plan_status") or task.get("status") or "").lower() == "completed":
                continue
            plans.append(task)
        return plans

    def _normalize_risk(self, risk_level: RiskLevel | str) -> RiskLevel:
        value = (risk_level or "low").strip().lower()
        if value not in {"low", "medium", "high"}:
            return "low"
        return value  # type: ignore[return-value]

    def _normalize_status(self, status: TaskStatus | str) -> TaskStatus:
        value = (status or "pending").strip().lower()
        allowed = {"pending", "in_progress", "completed", "blocked", "needs_approval"}
        if value not in allowed:
            return "pending"
        return value  # type: ignore[return-value]

    def create_task(
        self,
        title: str,
        description: str = "",
        risk_level: RiskLevel | str = "low",
        status: TaskStatus | str = "pending",
        approved_by_user: bool = False,
    ) -> dict[str, Any]:
        """Create a stored task and keep its metadata safe and visible."""
        safe_title = (title or "").strip()
        if not safe_title:
            raise ValueError("Task title is required.")

        risk = self._normalize_risk(risk_level)
        task_status = self._normalize_status(status)
        if task_status == "completed":
            task_status = "pending"

        if risk in {"medium", "high"} and not approved_by_user:
            task_status = "needs_approval"

        tasks = list_tasks(25)
        for item in tasks:
            if item.get("title") == safe_title and str(item.get("description") or "") == (description or ""):
                item["risk_level"] = risk
                item["approved_by_user"] = approved_by_user
                item["status"] = task_status
                item["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return item

        add_task(safe_title, description or "", status=task_status, risk_level=risk)
        tasks = list_tasks(25)
        for item in tasks:
            if item.get("title") == safe_title and str(item.get("description") or "") == (description or ""):
                item["risk_level"] = risk
                item["approved_by_user"] = approved_by_user
                item["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                item["updated_at"] = item["created_at"]
                return item
        return {
            "title": safe_title,
            "description": description or "",
            "status": task_status,
            "risk_level": risk,
            "approved_by_user": approved_by_user,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    def list_tasks(self, limit: int = 10, include_completed: bool = True) -> list[dict[str, Any]]:
        """Return stored tasks sorted newest-first, optionally hiding completed ones."""
        rows = list_tasks(limit=max(1, limit))
        if not include_completed:
            rows = [item for item in rows if str(item.get("status") or "").lower() != "completed"]
        return rows

    def approve_task(self, task_key: str) -> dict[str, Any]:
        """Approve a task so medium/high-risk jobs can proceed."""
        tasks = self.list_tasks(limit=50)
        for item in tasks:
            if item.get("key") == task_key:
                item["approved_by_user"] = True
                item["status"] = "pending"
                item["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                return item
        raise KeyError(f"Task '{task_key}' not found.")

    def complete_task(self, task_key: str) -> dict[str, Any]:
        """Mark a task complete while preserving its history."""
        res = complete_task(task_key)
        row = self._find_task(task_key)
        if row:
            row["status"] = "completed"
            row["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {"message": res, "task": row}

    def _find_task(self, task_key: str) -> dict[str, Any] | None:
        for item in self.list_tasks(limit=50):
            if item.get("key") == task_key:
                return item
        return None

    def evaluate_execution(self, task_key: str, approved_by_user: bool = False) -> dict[str, Any]:
        """Return whether this task is safe to execute automatically."""
        task = self._find_task(task_key)
        if not task:
            return {"allowed": False, "reason": "Task not found."}

        risk = str(task.get("risk_level") or "low").lower()
        if risk == "high" and not approved_by_user:
            return {"allowed": False, "reason": "High-risk task requires explicit approval."}
        if risk == "medium" and not approved_by_user:
            return {"allowed": False, "reason": "Medium-risk task requires approval."}

        return {"allowed": True, "reason": "Safe to execute automatically."}

    def add_follow_up(self, title: str, description: str = "", risk_level: RiskLevel | str = "low") -> dict[str, Any]:
        """Convenience wrapper for assistant follow-up tasks."""
        return self.create_task(title, description, risk_level=risk_level, approved_by_user=(self._normalize_risk(risk_level) == "low"))


__all__ = ["SafeTaskManager", "RiskLevel", "TaskStatus"]
