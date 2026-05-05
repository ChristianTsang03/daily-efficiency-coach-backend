from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from datetime import datetime, timedelta
from typing import Any, Dict, List
import os

from app.db import mongodb
from app.auth_utils import get_current_user_id
from app.ai.knowledge import KNOWLEDGE_BASE

from openai import OpenAI

router = APIRouter()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# -------------------------
# HELPERS
# -------------------------

def summarize_tasks(tasks: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(tasks)
    completed = sum(1 for t in tasks if t.get("status") == "done")
    skipped = sum(1 for t in tasks if t.get("status") == "skipped")
    postponed = sum(1 for t in tasks if t.get("status") == "postponed")

    return {
        "total": total,
        "completed": completed,
        "skipped": skipped,
        "postponed": postponed,
        "completion_rate": (completed / total) if total else 0,
    }


def summarize_habits(logs: List[Dict[str, Any]]) -> Dict[str, Any]:
    total = len(logs)
    done = sum(1 for l in logs if l.get("status") == "done")
    missed = sum(1 for l in logs if l.get("status") == "missed")

    return {
        "total_logs": total,
        "done": done,
        "missed": missed,
        "consistency": (done / total) if total else 0,
    }


def build_task_list(tasks: List[Dict[str, Any]]) -> str:
    if not tasks:
        return "No tasks this week."
    lines = []
    for t in tasks:
        title = t.get("title", "Untitled")
        status = t.get("status", "unknown")
        due = t.get("dueAt")
        category = t.get("category", "")
        priority = t.get("priority", "")
        due_str = due.strftime("%A %b %d") if isinstance(due, datetime) else (str(due)[:10] if due else "no deadline")
        cat_str = f" [{category}]" if category else ""
        pri_str = f" ({priority} priority)" if priority else ""
        lines.append(f"- {title}{cat_str}{pri_str} — {status}, due {due_str}")
    return "\n".join(lines)


def build_habit_list(logs: List[Dict[str, Any]]) -> str:
    if not logs:
        return "No habit logs this week."
    lines = []
    for l in logs:
        status = l.get("status", "unknown")
        date = l.get("date")
        date_str = date.strftime("%A %b %d") if isinstance(date, datetime) else str(date)[:10]
        lines.append(f"- {date_str}: {status}")
    return "\n".join(lines)


# -------------------------
# AI COACH
# -------------------------

@router.post("/coach")
async def ai_coach(
    payload: dict,
    user_id: str = Depends(get_current_user_id),
):
    user_question = payload.get("message")
    if not user_question:
        raise HTTPException(status_code=400, detail="Message is required")

    last_7_days = datetime.utcnow() - timedelta(days=7)

    tasks = await mongodb.collection("tasks").find({
        "userId": user_id,
        "createdAt": {"$gte": last_7_days}
    }).to_list(length=200)

    habit_logs = await mongodb.collection("habitLogs").find({
        "userId": user_id,
        "date": {"$gte": last_7_days}
    }).to_list(length=200)

    task_summary = summarize_tasks(tasks)
    habit_summary = summarize_habits(habit_logs)
    task_list = build_task_list(tasks)
    habit_list = build_habit_list(habit_logs)

    prompt = f"""
{KNOWLEDGE_BASE}

The user's tasks this week:
{task_list}

Task Summary:
- Total: {task_summary['total']}
- Completed: {task_summary['completed']}
- Skipped: {task_summary['skipped']}
- Postponed: {task_summary['postponed']}
- Completion rate: {round(task_summary['completion_rate'] * 100)}%

The user's habit logs this week:
{habit_list}

Habit Summary:
- Total logs: {habit_summary['total_logs']}
- Done: {habit_summary['done']}
- Missed: {habit_summary['missed']}
- Consistency: {round(habit_summary['consistency'] * 100)}%

The user asks: {user_question}

Respond naturally and specifically to what they asked based on their actual data.
Vary your response format based on the question — don't always use the same structure.
Reference specific task names and dates where relevant.
Do not use markdown formatting, bullet symbols, asterisks, or special characters. Write in plain text only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return {"answer": response.choices[0].message.content}


# -------------------------
# WEEKLY REFLECTION
# -------------------------

@router.get("/reflection")
async def weekly_reflection(
    user_id: str = Depends(get_current_user_id),
):
    last_7_days = datetime.utcnow() - timedelta(days=7)

    tasks = await mongodb.collection("tasks").find({
        "userId": user_id,
        "createdAt": {"$gte": last_7_days}
    }).to_list(length=500)

    habit_logs = await mongodb.collection("habitLogs").find({
        "userId": user_id,
        "date": {"$gte": last_7_days}
    }).to_list(length=500)

    task_summary = summarize_tasks(tasks)
    habit_summary = summarize_habits(habit_logs)
    task_list = build_task_list(tasks)
    habit_list = build_habit_list(habit_logs)

    prompt = f"""
{KNOWLEDGE_BASE}

Analyze this user's week based on their actual data:

Tasks this week:
{task_list}

Task Summary:
- Total: {task_summary['total']}
- Completed: {task_summary['completed']}
- Skipped: {task_summary['skipped']}
- Postponed: {task_summary['postponed']}
- Completion rate: {round(task_summary['completion_rate'] * 100)}%

Habit logs this week:
{habit_list}

Habit Summary:
- Total logs: {habit_summary['total_logs']}
- Done: {habit_summary['done']}
- Missed: {habit_summary['missed']}
- Consistency: {round(habit_summary['consistency'] * 100)}%

Write a weekly reflection covering:
- What worked well this week (be specific, reference actual tasks)
- What didn't work (be direct, not soft)
- Patterns you notice in their behavior
- Concrete steps to improve next week

Keep it concise and actionable. Reference specific task names where relevant.
Do not use markdown formatting, bullet symbols, asterisks, or special characters. Write in plain text only.
"""

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.7,
    )

    return {"reflection": response.choices[0].message.content}