const tg = window.Telegram.WebApp;
tg.expand();

const API_BASE = "https://your-railway-service.up.railway.app";

let currentTab = "active";
const listEl = document.getElementById("list");
const sectionTitle = document.getElementById("sectionTitle");

function initDataOrThrow() {
  const initData = tg.initData;
  if (!initData) {
    throw new Error("Telegram initData отсутствует. Откройте Mini App из Telegram.");
  }
  return initData;
}

async function api(path, options = {}) {
  const initData = initDataOrThrow();
  const headers = {
    "Content-Type": "application/json",
    "X-Telegram-Init-Data": initData,
    ...(options.headers || {}),
  };

  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  if (!response.ok) {
    const text = await response.text();
    throw new Error(text || "API error");
  }

  if (response.status === 204) return null;
  return response.json();
}

function formatDate(ts) {
  return new Date(ts * 1000).toLocaleString("ru-RU", { timeZone: "UTC" }) + " UTC";
}

function taskHtml(task) {
  return `
    <div class="task">
      <strong>${escapeHtml(task.title)}</strong>
      <div>${escapeHtml(task.description || "")}</div>
      <div class="meta">Дедлайн: ${formatDate(task.deadline)}</div>
      <div class="meta">Статус: ${task.status}</div>
      <div class="row">
        ${task.status === "active" ? `<button onclick="completeTask(${task.id})">Завершить</button>` : ""}
        <button class="delete" onclick="deleteTask(${task.id})">Удалить</button>
      </div>
    </div>
  `;
}

function escapeHtml(text) {
  return text
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

async function loadTasks() {
  if (currentTab === "leaderboard") {
    sectionTitle.textContent = "Лидерборд";
    const data = await api("/leaderboard");
    renderLeaderboard(data);
    return;
  }

  sectionTitle.textContent =
    currentTab === "active" ? "Активные задачи" : currentTab === "today" ? "Задачи на сегодня (UTC)" : "Завершённые задачи";

  const tasks = await api(`/tasks?filter=${currentTab}`);
  if (!tasks.length) {
    listEl.innerHTML = `<p class="note">Список пуст.</p>`;
    return;
  }
  listEl.innerHTML = tasks.map(taskHtml).join("");
}

function renderLeaderboard(data) {
  const rows = data.top
    .map((item) => `<div class="task">#${item.rank} — user_id ${item.user_id}: ${item.completed_count}</div>`)
    .join("");

  const current = data.current_user
    ? `<div class="task"><strong>Вы:</strong> #${data.current_user.rank}, задач: ${data.current_user.completed_count}</div>`
    : `<div class="task">Вы пока не завершили ни одной задачи.</div>`;

  listEl.innerHTML = rows + current;
}

async function createTask(event) {
  event.preventDefault();
  const title = document.getElementById("title").value.trim();
  const description = document.getElementById("description").value.trim();
  const deadlineRaw = document.getElementById("deadline").value;

  if (!title || !deadlineRaw) return;

  const deadlineTs = Math.floor(new Date(deadlineRaw).getTime() / 1000);
  await api("/tasks", {
    method: "POST",
    body: JSON.stringify({ title, description, deadline: deadlineTs }),
  });

  event.target.reset();
  currentTab = "active";
  setActiveTab();
  await loadTasks();
}

async function completeTask(id) {
  await api(`/tasks/${id}/complete`, { method: "POST" });
  await loadTasks();
}

async function deleteTask(id) {
  await api(`/tasks/${id}`, { method: "DELETE" });
  await loadTasks();
}

window.completeTask = completeTask;
window.deleteTask = deleteTask;

function setActiveTab() {
  document.querySelectorAll(".tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === currentTab);
  });
}

document.getElementById("taskForm").addEventListener("submit", async (e) => {
  try {
    await createTask(e);
  } catch (err) {
    tg.showAlert(`Ошибка: ${err.message}`);
  }
});

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", async () => {
    currentTab = btn.dataset.tab;
    setActiveTab();
    try {
      await loadTasks();
    } catch (err) {
      tg.showAlert(`Ошибка: ${err.message}`);
    }
  });
});

loadTasks().catch((err) => {
  tg.showAlert(`Ошибка загрузки: ${err.message}`);
});
