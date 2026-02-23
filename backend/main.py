import asyncio
import hashlib
import hmac
import json
import os
import sqlite3
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import parse_qsl

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN", "")
FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "https://example.com")
TIMEZONE = os.getenv("TIMEZONE", "UTC")  # Для фильтра "сегодня" используем UTC по умолчанию.
DATABASE_PATH = os.getenv("DATABASE_PATH", "tasks.db")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is required")


@contextmanager
def db_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    with db_conn() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                deadline INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                created_at INTEGER NOT NULL,
                completed_at INTEGER,
                notified_24h INTEGER NOT NULL DEFAULT 0,
                notified_1h INTEGER NOT NULL DEFAULT 0,
                notified_deadline INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        conn.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    scheduler_task = asyncio.create_task(scheduler_loop())
    try:
        yield
    finally:
        scheduler_task.cancel()
        try:
            await scheduler_task
        except asyncio.CancelledError:
            pass


app = FastAPI(title="Telegram Mini App Daily Planner API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[FRONTEND_ORIGIN, "https://web.telegram.org"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def parse_init_data(init_data: str) -> Dict[str, str]:
    return dict(parse_qsl(init_data, keep_blank_values=True))


def validate_init_data(init_data: str) -> Dict[str, Any]:
    data = parse_init_data(init_data)
    received_hash = data.pop("hash", None)
    if not received_hash:
        raise HTTPException(status_code=401, detail="Missing hash in initData")

    check_string = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret_key = hmac.new(
        key=b"WebAppData", msg=BOT_TOKEN.encode("utf-8"), digestmod=hashlib.sha256
    ).digest()
    calculated_hash = hmac.new(
        key=secret_key, msg=check_string.encode("utf-8"), digestmod=hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(calculated_hash, received_hash):
        raise HTTPException(status_code=401, detail="Invalid initData")

    user_raw = data.get("user")
    if not user_raw:
        raise HTTPException(status_code=401, detail="Missing user in initData")

    try:
        user_obj = json.loads(user_raw)
        user_id = int(user_obj["id"])
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=401, detail="Invalid user payload") from exc

    return {"user_id": user_id, "user": user_obj}


async def get_current_user_id(x_telegram_init_data: Optional[str] = Header(default=None)) -> int:
    if not x_telegram_init_data:
        raise HTTPException(status_code=401, detail="X-Telegram-Init-Data header is required")
    auth = validate_init_data(x_telegram_init_data)
    return auth["user_id"]


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=2000)
    deadline: int = Field(description="UTC timestamp in seconds")


class TaskOut(BaseModel):
    id: int
    user_id: int
    title: str
    description: str
    deadline: int
    status: str
    created_at: int
    completed_at: Optional[int]
    notified_24h: bool
    notified_1h: bool
    notified_deadline: bool


class LeaderboardItem(BaseModel):
    user_id: int
    completed_count: int
    rank: int


class LeaderboardResponse(BaseModel):
    top: List[LeaderboardItem]
    current_user: Optional[LeaderboardItem]


def row_to_task(row: sqlite3.Row) -> TaskOut:
    return TaskOut(
        id=row["id"],
        user_id=row["user_id"],
        title=row["title"],
        description=row["description"] or "",
        deadline=row["deadline"],
        status=row["status"],
        created_at=row["created_at"],
        completed_at=row["completed_at"],
        notified_24h=bool(row["notified_24h"]),
        notified_1h=bool(row["notified_1h"]),
        notified_deadline=bool(row["notified_deadline"]),
    )


@app.post("/tasks", response_model=TaskOut)
async def create_task(payload: TaskCreate, user_id: int = Depends(get_current_user_id)) -> TaskOut:
    now_ts = int(datetime.now(timezone.utc).timestamp())
    with db_conn() as conn:
        cur = conn.execute(
            """
            INSERT INTO tasks (user_id, title, description, deadline, status, created_at)
            VALUES (?, ?, ?, ?, 'active', ?)
            """,
            (user_id, payload.title.strip(), payload.description.strip(), payload.deadline, now_ts),
        )
        task_id = cur.lastrowid
        conn.commit()

        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    return row_to_task(row)


@app.get("/tasks", response_model=List[TaskOut])
async def list_tasks(
    filter: str = Query(default="active", pattern="^(active|today|completed)$"),
    user_id: int = Depends(get_current_user_id),
) -> List[TaskOut]:
    now_utc = datetime.now(timezone.utc)
    start_of_day = datetime(now_utc.year, now_utc.month, now_utc.day, tzinfo=timezone.utc)
    end_of_day = start_of_day + timedelta(days=1)
    start_ts = int(start_of_day.timestamp())
    end_ts = int(end_of_day.timestamp())

    query = "SELECT * FROM tasks WHERE user_id = ?"
    params: List[Any] = [user_id]

    if filter == "active":
        query += " AND status = 'active'"
    elif filter == "today":
        query += " AND status = 'active' AND deadline >= ? AND deadline < ?"
        params.extend([start_ts, end_ts])
    else:
        query += " AND status = 'completed'"

    query += " ORDER BY deadline ASC"

    with db_conn() as conn:
        rows = conn.execute(query, tuple(params)).fetchall()

    return [row_to_task(row) for row in rows]


@app.post("/tasks/{task_id}/complete", response_model=TaskOut)
async def complete_task(task_id: int, user_id: int = Depends(get_current_user_id)) -> TaskOut:
    completed_at = int(datetime.now(timezone.utc).timestamp())
    with db_conn() as conn:
        row = conn.execute(
            "SELECT * FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Task not found")

        conn.execute(
            """
            UPDATE tasks
            SET status = 'completed', completed_at = ?
            WHERE id = ? AND user_id = ?
            """,
            (completed_at, task_id, user_id),
        )
        conn.commit()
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()

    return row_to_task(updated)


@app.delete("/tasks/{task_id}")
async def delete_task(task_id: int, user_id: int = Depends(get_current_user_id)) -> Dict[str, bool]:
    with db_conn() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id))
        conn.commit()
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"ok": True}


@app.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(user_id: int = Depends(get_current_user_id)) -> LeaderboardResponse:
    with db_conn() as conn:
        top_rows = conn.execute(
            """
            SELECT user_id, COUNT(*) AS completed_count
            FROM tasks
            WHERE status = 'completed'
            GROUP BY user_id
            ORDER BY completed_count DESC, user_id ASC
            LIMIT 10
            """
        ).fetchall()

        all_rows = conn.execute(
            """
            SELECT user_id, COUNT(*) AS completed_count
            FROM tasks
            WHERE status = 'completed'
            GROUP BY user_id
            ORDER BY completed_count DESC, user_id ASC
            """
        ).fetchall()

    ranked_all: List[Tuple[int, int, int]] = []
    for idx, row in enumerate(all_rows, start=1):
        ranked_all.append((idx, row["user_id"], row["completed_count"]))

    top = [
        LeaderboardItem(user_id=row["user_id"], completed_count=row["completed_count"], rank=i)
        for i, row in enumerate(top_rows, start=1)
    ]

    current = None
    for rank, uid, cnt in ranked_all:
        if uid == user_id:
            current = LeaderboardItem(user_id=uid, completed_count=cnt, rank=rank)
            break

    return LeaderboardResponse(top=top, current_user=current)


async def send_telegram_message(chat_id: int, text: str) -> None:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    async with httpx.AsyncClient(timeout=10) as client:
        await client.post(url, json={"chat_id": chat_id, "text": text})


async def scheduler_loop() -> None:
    while True:
        await process_deadline_notifications()
        await asyncio.sleep(60)


async def process_deadline_notifications() -> None:
    now_ts = int(datetime.now(timezone.utc).timestamp())

    with db_conn() as conn:
        rows = conn.execute("SELECT * FROM tasks WHERE status = 'active'").fetchall()

        updates: List[Tuple[str, Tuple[Any, ...]]] = []
        messages: List[Tuple[int, str]] = []

        for row in rows:
            task_id = row["id"]
            user_id = row["user_id"]
            title = row["title"]
            deadline = row["deadline"]
            diff = deadline - now_ts

            if diff <= 0 and not row["notified_deadline"]:
                updates.append(
                    (
                        """
                        UPDATE tasks
                        SET status = 'completed', completed_at = ?, notified_deadline = 1
                        WHERE id = ?
                        """,
                        (now_ts, task_id),
                    )
                )
                messages.append((user_id, f"⏰ Дедлайн наступил: {title}. Задача автоматически завершена."))
                continue

            if 0 < diff <= 3600 and not row["notified_1h"]:
                updates.append(("UPDATE tasks SET notified_1h = 1 WHERE id = ?", (task_id,)))
                messages.append((user_id, f"⌛ До дедлайна задачи '{title}' остался 1 час."))

            if 3600 < diff <= 86400 and not row["notified_24h"]:
                updates.append(("UPDATE tasks SET notified_24h = 1 WHERE id = ?", (task_id,)))
                messages.append((user_id, f"📌 До дедлайна задачи '{title}' осталось 24 часа."))

        for q, p in updates:
            conn.execute(q, p)
        conn.commit()

    for chat_id, text in messages:
        try:
            await send_telegram_message(chat_id, text)
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
