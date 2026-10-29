/* SprintBoard frontend — browser-native JS, no dependencies. */
(function () {
  "use strict";

  var API_BASE = "";
  var currentFilter = "all";
  var tasks = [];

  // ----- element lookups -----
  var el = {
    health: document.getElementById("health-indicator"),
    healthLabel: document.querySelector("#health-indicator .health-label"),
    statTotal: document.getElementById("stat-total"),
    statTodo: document.getElementById("stat-todo"),
    statDoing: document.getElementById("stat-doing"),
    statDone: document.getElementById("stat-done"),
    form: document.getElementById("task-form"),
    title: document.getElementById("task-title"),
    priority: document.getElementById("task-priority"),
    addBtn: document.getElementById("add-task-btn"),
    formError: document.getElementById("form-error"),
    filters: document.getElementById("filters"),
    loading: document.getElementById("loading"),
    error: document.getElementById("error"),
    empty: document.getElementById("empty"),
    list: document.getElementById("task-list")
  };

  // ----- helpers -----
  function setState(note, visible) {
    note.hidden = !visible;
  }

  function clearStates() {
    setState(el.loading, false);
    setState(el.error, false);
    setState(el.empty, false);
  }

  function api(path, options) {
    return fetch(API_BASE + path, options).then(function (resp) {
      if (resp.status === 204) return { status: resp.status, data: null };
      return resp
        .json()
        .catch(function () { return null; })
        .then(function (data) {
          if (!resp.ok) {
            var message =
              data && data.error ? data.error : "Request failed (" + resp.status + ")";
            var err = new Error(message);
            err.status = resp.status;
            throw err;
          }
          return { status: resp.status, data: data };
        });
    });
  }

  // ----- health -----
  function checkHealth() {
    api("/api/health")
      .then(function () {
        el.health.classList.add("ok");
        el.health.classList.remove("down");
        el.healthLabel.textContent = "API online";
      })
      .catch(function () {
        el.health.classList.add("down");
        el.health.classList.remove("ok");
        el.healthLabel.textContent = "API offline";
      });
  }

  // ----- stats -----
  function renderStats() {
    var counts = { total: 0, todo: 0, doing: 0, done: 0 };
    tasks.forEach(function (t) {
      counts.total += 1;
      if (counts[t.status] !== undefined) counts[t.status] += 1;
    });
    el.statTotal.textContent = counts.total;
    el.statTodo.textContent = counts.todo;
    el.statDoing.textContent = counts.doing;
    el.statDone.textContent = counts.done;
  }

  // ----- task list -----
  function visibleTasks() {
    if (currentFilter === "all") return tasks;
    return tasks.filter(function (t) { return t.status === currentFilter; });
  }

  function taskCard(task) {
    var li = document.createElement("li");
    li.className = "task-card";
    li.setAttribute("data-id", task.id);
    li.setAttribute("data-status", task.status);

    var main = document.createElement("div");
    main.className = "task-main";

    var title = document.createElement("p");
    title.className = "task-title";
    title.textContent = task.title;
    main.appendChild(title);

    var meta = document.createElement("div");
    meta.className = "task-meta";

    var prio = document.createElement("span");
    prio.className = "badge priority-" + task.priority;
    prio.textContent = task.priority;
    meta.appendChild(prio);

    var status = document.createElement("span");
    status.className = "badge status-" + task.status;
    status.textContent = task.status;
    meta.appendChild(status);

    main.appendChild(meta);
    li.appendChild(main);

    var actions = document.createElement("div");
    actions.className = "task-actions";

    ["todo", "doing", "done"].forEach(function (s) {
      var btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-status" + (task.status === s ? " current" : "");
      btn.setAttribute("data-action", "set-status");
      btn.setAttribute("data-status", s);
      btn.textContent = s;
      if (task.status === s) btn.disabled = true;
      btn.addEventListener("click", function () { updateTaskStatus(task.id, s); });
      actions.appendChild(btn);
    });

    var del = document.createElement("button");
    del.type = "button";
    del.className = "btn-delete";
    del.setAttribute("data-action", "delete");
    del.setAttribute("aria-label", "Delete task: " + task.title);
    del.textContent = "Delete";
    del.addEventListener("click", function () { deleteTask(task.id, li); });
    actions.appendChild(del);

    li.appendChild(actions);
    return li;
  }

  function renderTasks() {
    renderStats();
    el.list.innerHTML = "";
    var visible = visibleTasks();
    visible.forEach(function (task) {
      el.list.appendChild(taskCard(task));
    });
    setState(el.empty, visible.length === 0);
  }

  function loadTasks() {
    api("/api/stats").then(function(r){}).catch(function(){});
    setState(el.loading, true);
    setState(el.error, false);
    setState(el.empty, false);
    api("/api/tasks")
      .then(function (res) {
        tasks = (res.data && res.data.tasks) || [];
        clearStates();
        renderTasks();
      })
      .catch(function () {
        clearStates();
        setState(el.error, true);
        tasks = [];
        renderStats();
      });
  }

  // ----- actions -----
  function refreshFromApi() {
    api("/api/tasks")
      .then(function (res) {
        tasks = (res.data && res.data.tasks) || [];
        renderTasks();
      })
      .catch(function () {});
  }

  function updateTaskStatus(id, status) {
    api("/api/tasks/" + id, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ status: status })
    })
      .then(refreshFromApi)
      .catch(function (err) {
        if (err.status === 404) refreshFromApi();
      });
  }

  function deleteTask(id, node) {
    node.classList.add("removing");
    api("/api/tasks/" + id, { method: "DELETE" })
      .then(function () {
        tasks = tasks.filter(function (t) { return t.id !== id; });
        renderTasks();
      })
      .catch(function (err) {
        node.classList.remove("removing");
        if (err.status === 404) refreshFromApi();
      });
  }

  function submitHandler(event) {
    event.preventDefault();
    var title = el.title.value.trim();
    setState(el.formError, false);
    if (!title) {
      el.formError.textContent = "Please enter a non-blank task title.";
      setState(el.formError, true);
      el.title.focus();
      return;
    }
    var payload = { title: title, priority: el.priority.value };
    el.addBtn.disabled = true;
    api("/api/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    })
      .then(function (res) {
        tasks.unshift(res.data.task);
        el.title.value = "";
        el.title.focus();
        renderTasks();
        checkHealth();
      })
      .catch(function (err) {
        el.formError.textContent = err.message || "Could not create the task.";
        setState(el.formError, true);
      })
      .then(function () {
        el.addBtn.disabled = false;
      });
  }

  function filterHandler(event) {
    var btn = event.target.closest(".filter-btn");
    if (!btn) return;
    currentFilter = btn.getAttribute("data-filter");
    Array.prototype.forEach.call(el.filters.querySelectorAll(".filter-btn"), function (b) {
      b.classList.toggle("active", b === btn);
    });
    renderTasks();
  }

  // ----- wiring -----
  el.form.addEventListener("submit", submitHandler);
  el.filters.addEventListener("click", filterHandler);

  checkHealth();
  loadTasks();
  window.setInterval(checkHealth, 15000);
})();
