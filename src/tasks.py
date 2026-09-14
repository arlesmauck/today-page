"""Persistent task storage for the dashboard."""
import json
import os
import threading
from datetime import date, datetime, timedelta
from uuid import uuid4

from src.app_settings import get_timezone
from src.config import DATA_DIR


TASKS_FILE = DATA_DIR / "tasks.json"
MAX_TASK_LENGTH = 160
_TASKS_LOCK = threading.Lock()


def _today() -> date:
    """Return today's date in the dashboard's configured timezone."""
    return datetime.now(get_timezone()).date()


def _parse_date(value: object) -> date | None:
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _week_start(day: date) -> date:
    """Use a Monday-based week for weekly task cleanup."""
    return day - timedelta(days=day.weekday())


def _read_tasks_unlocked() -> list[dict]:
    if not TASKS_FILE.exists():
        return []

    try:
        payload = json.loads(TASKS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return []

    raw_tasks = payload.get("tasks", []) if isinstance(payload, dict) else payload
    if not isinstance(raw_tasks, list):
        return []

    tasks = []
    for raw in raw_tasks:
        if not isinstance(raw, dict):
            continue
        raw_text = raw.get("text")
        if not isinstance(raw_text, str):
            continue
        text = raw_text.strip()
        created_date = raw.get("createdDate")
        if not text or not _parse_date(created_date):
            continue

        completed = raw.get("completed") is True
        completed_date = raw.get("completedDate")
        if completed_date is not None and not _parse_date(completed_date):
            completed_date = None

        tasks.append({
            "id": str(raw.get("id") or uuid4()),
            "text": text[:MAX_TASK_LENGTH],
            "createdDate": created_date,
            "completed": completed,
            "completedDate": completed_date,
        })
    return tasks


def _write_tasks_unlocked(tasks: list[dict]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp_file = TASKS_FILE.with_name(f".{TASKS_FILE.name}.{os.getpid()}.tmp")
    try:
        temp_file.write_text(json.dumps({"version": 1, "tasks": tasks}, indent=2) + "\n")
        os.replace(temp_file, TASKS_FILE)
    finally:
        temp_file.unlink(missing_ok=True)


def _clean_tasks(tasks: list[dict], today: date) -> list[dict]:
    """Remove completed tasks from prior days and tasks from prior weeks."""
    week_start = _week_start(today)
    cleaned = []

    for task in tasks:
        created = _parse_date(task.get("createdDate"))
        if created is None or created < week_start or created > today:
            continue

        if task.get("completed"):
            completed = _parse_date(task.get("completedDate")) or created
            if completed < today:
                continue

        cleaned.append(task)
    return cleaned


def load_tasks() -> list[dict]:
    """Load tasks and apply date-based cleanup before returning them."""
    with _TASKS_LOCK:
        tasks = _read_tasks_unlocked()
        cleaned = _clean_tasks(tasks, _today())
        if cleaned != tasks:
            _write_tasks_unlocked(cleaned)
        return cleaned


def create_task(text: str) -> dict:
    """Create a new task for today."""
    value = text.strip()
    if not value:
        raise ValueError("Task text must not be empty")
    if len(value) > MAX_TASK_LENGTH:
        raise ValueError(f"Task text must be {MAX_TASK_LENGTH} characters or fewer")

    with _TASKS_LOCK:
        today = _today()
        tasks = _clean_tasks(_read_tasks_unlocked(), today)
        task = {
            "id": str(uuid4()),
            "text": value,
            "createdDate": today.isoformat(),
            "completed": False,
            "completedDate": None,
        }
        tasks.append(task)
        _write_tasks_unlocked(tasks)
        return task


def set_task_completed(task_id: str, completed: bool) -> dict | None:
    """Set a task's completion state, or return None when it no longer exists."""
    with _TASKS_LOCK:
        today = _today()
        tasks = _clean_tasks(_read_tasks_unlocked(), today)
        task = next((item for item in tasks if item["id"] == task_id), None)
        if task is None:
            return None

        task["completed"] = completed
        task["completedDate"] = today.isoformat() if completed else None
        _write_tasks_unlocked(tasks)
        return task
