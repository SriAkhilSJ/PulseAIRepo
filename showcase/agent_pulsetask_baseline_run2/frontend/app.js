/* PulseTask frontend — talks to the Python backend REST API. */
(() => {
  "use strict";

  const API = {
    health: "/api/health",
    tasks: "/api/tasks",
    stats: "/api/stats",
  };

  const STATUS_LABELS = { todo: "To Do", doing: "Doing", done: "Done" };

  const el = {
    connection: document.getElementById("connection"),
    statTotal: document.getElementById("stat-total"),
    statTodo: document.getElementById("stat-todo"),
    statDoing: document.getElementById("stat-doing"),
    statDone: document.getElementById("stat-done"),
    form: document.getElementById("add-task-form"),
    titleInput: document.getElementById("task-title"),
    statusSelect: document.getElementById("task-status"),
    formError: document.getElementById("form-error"),
    boardError: document.getElementById("board-error"),
    board: document.getElementById("board"),
    columns: {
      todo: document.getElementById("col-todo"),
      doing: document.getElementById("col-doing"),
      done: document.getElementById("col-done"),
    },
    counts: document.querySelectorAll("[data-count]"),
  };

  function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value;
    return div.innerHTML;
  }

  function showError(target, message) {
    target.textContent = message;
    target.hidden = false;
  }

  async function apiFetch(path, options = {}) {
    let response;
    try {
      response = await fetch(path, {
        headers: { "Content-Type": "application/json" },
        ...options,
      });
    } catch (err) {
      throw new Error("Network error: is the backend running on this port?");
    }
    let data = null;
    const text = await response.text();
    if (text) {
      try {
        data = JSON.parse(text);
      } catch (err) {
        /* non-JSON response body */
      }
    }
    if (!response.ok) {
      const message = (data && data.error) || `Request failed (${response.status})`;
      throw new Error(message);
    }
    return data;
  }

  function setConnection(state, text) {
    el.connection.dataset.state = state;
    el.connection.textContent = text;
  }

  function renderTasks(tasks) {
    for (const status of Object.keys(el.columns)) {
      el.columns[status].innerHTML = "";
    }
    for (const task of tasks) {
      const column = el.columns[task.status];
      if (!column) continue;
      const card = document.createElement("article");
      card.className = "task-card";
      card.dataset.id = task.id;
      card.innerHTML = `
        <p class="task-title">${escapeHtml(task.title)}</p>
        <div class="task-actions">
          <select class="task-status" aria-label="Change status">
            ${Object.entries(STATUS_LABELS)
              .map(
                ([value, label]) =>
                  `<option value="${value}" ${value === task.status ? "selected" : ""}>${label}</option>`
              )
              .join("")}
          </select>
          <button type="button" class="btn btn-danger task-delete" aria-label="Delete task">Delete</button>
        </div>`;
      column.appendChild(card);
    }
    for (const span of el.counts) {
      const status = span.dataset.count;
      span.textContent = String(tasks.filter((t) => t.status === status).length);
    }
  }

  function renderStats(stats) {
    el.statTotal.textContent = stats.total;
    el.statTodo.textContent = stats.todo;
    el.statDoing.textContent = stats.doing;
    el.statDone.textContent = stats.done;
  }

  async function refresh() {
    const [tasksPayload, stats] = await Promise.all([
      apiFetch(API.tasks),
      apiFetch(API.stats),
    ]);
    renderTasks(tasksPayload.tasks || []);
    renderStats(stats);
    setConnection("online", "connected");
    el.boardError.hidden = true;
  }

  async function checkHealth() {
    try {
      const health = await apiFetch(API.health);
      setConnection(
        health.status === "ok" ? "online" : "degraded",
        health.status === "ok" ? "connected" : "db unavailable"
      );
    } catch (err) {
      setConnection("offline", "offline");
    }
  }

  el.board.addEventListener("change", async (event) => {
    const select = event.target.closest(".task-status");
    if (!select) return;
    const card = select.closest(".task-card");
    try {
      await apiFetch(`${API.tasks}/${card.dataset.id}`, {
        method: "PATCH",
        body: JSON.stringify({ status: select.value }),
      });
      await refresh();
    } catch (err) {
      showError(el.boardError, err.message);
      await refresh();
    }
  });

  el.board.addEventListener("click", async (event) => {
    const button = event.target.closest(".task-delete");
    if (!button) return;
    const card = button.closest(".task-card");
    try {
      await apiFetch(`${API.tasks}/${card.dataset.id}`, { method: "DELETE" });
      await refresh();
    } catch (err) {
      showError(el.boardError, err.message);
    }
  });

  el.form.addEventListener("submit", async (event) => {
    event.preventDefault();
    el.formError.hidden = true;
    const title = el.titleInput.value.trim();
    if (!title) {
      showError(el.formError, "Please enter a task title.");
      return;
    }
    try {
      await apiFetch(API.tasks, {
        method: "POST",
        body: JSON.stringify({ title, status: el.statusSelect.value }),
      });
      el.form.reset();
      el.statusSelect.value = "todo";
      await refresh();
    } catch (err) {
      showError(el.formError, err.message);
    }
  });

  (async function init() {
    await checkHealth();
    try {
      await refresh();
    } catch (err) {
      showError(el.boardError, err.message);
    }
  })();
})();
