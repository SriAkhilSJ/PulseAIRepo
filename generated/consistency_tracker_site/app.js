/* ============================================================
   Consistency Tracker — app.js
   localStorage persistence, streaks, percentages, weekly
   progress, notes. Vanilla JavaScript only.
   ============================================================ */

(function () {
  "use strict";

  /* ---------- Constants & state ---------- */
  var STORAGE_HABITS_KEY = "consistencyTracker.habits";
  var STORAGE_NOTES_KEY = "consistencyTracker.notes";

  var WEEKDAY_NAMES = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var WEEKDAY_FULL = [
    "Sunday", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday"
  ];
  var MONTH_NAMES = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December"
  ];

  var state = {
    habits: loadHabits(),
    notes: loadNotes()
  };

  /* ---------- Element references ---------- */
  var els = {
    todayLabel: document.getElementById("today-label"),
    statBestStreak: document.getElementById("stat-best-streak"),
    statCurrentStreak: document.getElementById("stat-current-streak"),
    statToday: document.getElementById("stat-today"),
    statWeek: document.getElementById("stat-week"),
    form: document.getElementById("add-habit-form"),
    habitInput: document.getElementById("habit-name"),
    habitList: document.getElementById("habit-list"),
    emptyState: document.getElementById("empty-state"),
    habitsHint: document.getElementById("habits-hint"),
    weekdayLabels: document.getElementById("weekday-labels"),
    weekBars: document.getElementById("week-bars"),
    weekSummary: document.getElementById("week-summary"),
    notesInput: document.getElementById("notes-input"),
    notesSaved: document.getElementById("notes-saved")
  };

  /* ---------- Date helpers (local timezone) ---------- */
  function dateKey(d) {
    var y = d.getFullYear();
    var m = String(d.getMonth() + 1).padStart(2, "0");
    var day = String(d.getDate()).padStart(2, "0");
    return y + "-" + m + "-" + day;
  }

  function todayKey() {
    return dateKey(new Date());
  }

  function keyForOffset(offsetDays) {
    var d = new Date();
    d.setDate(d.getDate() - offsetDays);
    return dateKey(d);
  }

  /* ---------- Persistence ---------- */
  function loadHabits() {
    try {
      var raw = localStorage.getItem(STORAGE_HABITS_KEY);
      var parsed = raw ? JSON.parse(raw) : [];
      if (!Array.isArray(parsed)) return [];
      // Normalize entries: ensure id/name/completions exist.
      return parsed
        .filter(function (h) { return h && typeof h.name === "string"; })
        .map(function (h) {
          return {
            id: typeof h.id === "string" ? h.id : String(Date.now() + Math.random()),
            name: h.name,
            createdAt: h.createdAt || todayKey(),
            completions: Array.isArray(h.completions) ? h.completions : []
          };
        });
    } catch (e) {
      return [];
    }
  }

  function saveHabits() {
    try {
      localStorage.setItem(STORAGE_HABITS_KEY, JSON.stringify(state.habits));
    } catch (e) {
      // localStorage unavailable (private mode / quota) — degrade silently.
    }
  }

  function loadNotes() {
    try {
      var raw = localStorage.getItem(STORAGE_NOTES_KEY);
      var parsed = raw ? JSON.parse(raw) : {};
      return parsed && typeof parsed === "object" ? parsed : {};
    } catch (e) {
      return {};
    }
  }

  function saveNotes() {
    try {
      localStorage.setItem(STORAGE_NOTES_KEY, JSON.stringify(state.notes));
    } catch (e) {
      // ignore
    }
  }

  /* ---------- Habit helpers ---------- */
  function isCompletedOn(habit, key) {
    return habit.completions.indexOf(key) !== -1;
  }

  function setCompletedOn(habit, key, completed) {
    if (completed) {
      if (!isCompletedOn(habit, key)) habit.completions.push(key);
    } else {
      habit.completions = habit.completions.filter(function (k) { return k !== key; });
    }
  }

  /**
   * Compute streak info for a habit.
   * current: consecutive days ending today (or yesterday if today not yet done).
   * best: longest run of consecutive completed days.
   */
  function computeStreaks(habit) {
    var completions = habit.completions.slice().sort();
    var current = 0;
    var best = 0;

    var idx = completions.length - 1;
    var expected = todayKey();

    // If today isn't completed, allow the streak to count up to yesterday.
    if (idx >= 0 && completions[idx] !== expected) {
      expected = keyForOffset(1);
    }

    while (idx >= 0 && completions[idx] === expected) {
      current += 1;
      idx -= 1;
      expected = keyForOffset(current);
    }

    // Best streak: walk the sorted date list and count consecutive runs.
    var run = 1;
    for (var i = 1; i < completions.length; i++) {
      var prev = new Date(completions[i - 1] + "T00:00:00");
      var curr = new Date(completions[i] + "T00:00:00");
      var diffDays = Math.round((curr - prev) / 86400000);
      if (diffDays === 1) {
        run += 1;
      } else {
        if (run > best) best = run;
        run = 1;
      }
    }
    if (completions.length > 0 && run > best) best = run;

    return { current: current, best: best };
  }

  /* ---------- Rendering ---------- */
  function render() {
    renderHeader();
    renderStats();
    renderHabitList();
    renderWeeklyProgress();
    renderNotes();
  }

  function renderHeader() {
    var now = new Date();
    els.todayLabel.textContent =
      WEEKDAY_FULL[now.getDay()] + ", " +
      MONTH_NAMES[now.getMonth()] + " " + now.getDate();
  }

  function renderStats() {
    var count = state.habits.length;

    // Today's completion percentage.
    var doneToday = state.habits.filter(function (h) {
      return isCompletedOn(h, todayKey());
    }).length;
    var todayPct = count > 0 ? Math.round((doneToday / count) * 100) : 0;

    // Overall current/best streaks = best across habits.
    var currentStreak = 0;
    var bestStreak = 0;
    state.habits.forEach(function (h) {
      var s = computeStreaks(h);
      if (s.current > currentStreak) currentStreak = s.current;
      if (s.best > bestStreak) bestStreak = s.best;
    });

    // Weekly completion percentage over the last 7 days.
    var weekTotal = 0;
    var weekPossible = count * 7;
    for (var i = 0; i < 7; i++) {
      var key = keyForOffset(i);
      state.habits.forEach(function (h) {
        if (isCompletedOn(h, key)) weekTotal += 1;
      });
    }
    var weekPct = weekPossible > 0 ? Math.round((weekTotal / weekPossible) * 100) : 0;

    els.statBestStreak.textContent = String(bestStreak) + "d";
    els.statCurrentStreak.textContent = String(currentStreak) + "d";
    els.statToday.textContent = todayPct + "%";
    els.statWeek.textContent = weekPct + "%";
  }

  function renderHabitList() {
    els.habitList.textContent = "";

    if (state.habits.length === 0) {
      els.emptyState.classList.remove("hidden");
      els.habitsHint.textContent = "Add your first habit to get started.";
      return;
    }

    els.emptyState.classList.add("hidden");
    els.habitsHint.textContent = "Mark what you completed today.";

    var today = todayKey();

    state.habits.forEach(function (habit) {
      var li = document.createElement("li");
      li.className = "habit-item";
      if (isCompletedOn(habit, today)) li.classList.add("completed");

      // Checkbox
      var checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.className = "habit-check";
      checkbox.checked = isCompletedOn(habit, today);
      checkbox.setAttribute("aria-label", "Completed " + habit.name + " today");
      checkbox.dataset.id = habit.id;

      // Info block
      var info = document.createElement("div");
      info.className = "habit-info";

      var name = document.createElement("span");
      name.className = "habit-name";
      name.textContent = habit.name;

      var meta = document.createElement("div");
      meta.className = "habit-meta";
      var streaks = computeStreaks(habit);

      var streakBadge = document.createElement("span");
      streakBadge.className = "badge";
      streakBadge.textContent = "🔥 " + streaks.current + " day streak";

      var bestBadge = document.createElement("span");
      bestBadge.className = "badge";
      bestBadge.textContent = "Best: " + streaks.best + "d";

      meta.appendChild(streakBadge);
      meta.appendChild(bestBadge);
      info.appendChild(name);
      info.appendChild(meta);

      // Delete button
      var del = document.createElement("button");
      del.type = "button";
      del.className = "btn btn-danger";
      del.textContent = "Delete";
      del.setAttribute("aria-label", "Delete " + habit.name);
      del.dataset.id = habit.id;

      li.appendChild(checkbox);
      li.appendChild(info);
      li.appendChild(del);
      els.habitList.appendChild(li);
    });
  }

  function renderWeeklyProgress() {
    els.weekdayLabels.textContent = "";
    els.weekBars.textContent = "";

    var labels = [];
    var bars = [];
    var count = state.habits.length;

    // Last 7 days: offset 6 = oldest, offset 0 = today.
    for (var offset = 6; offset >= 0; offset--) {
      var d = new Date();
      d.setDate(d.getDate() - offset);
      var key = keyForOffset(offset);

      var label = document.createElement("span");
      label.textContent = WEEKDAY_NAMES[d.getDay()];
      labels.push(label);

      var track = document.createElement("span");
      track.className = "bar-track";

      var fill = document.createElement("span");
      fill.className = "bar-fill";
      var done = 0;
      state.habits.forEach(function (h) {
        if (isCompletedOn(h, key)) done += 1;
      });
      var pct = count > 0 ? Math.round((done / count) * 100) : 0;
      fill.style.width = pct + "%";
      fill.setAttribute("aria-hidden", "true");
      track.appendChild(fill);
      bars.push(track);
    }

    labels.forEach(function (l) { els.weekdayLabels.appendChild(l); });
    bars.forEach(function (b) { els.weekBars.appendChild(b); });

    // Summary line.
    var completedDays = 0;
    for (var i = 0; i < 7; i++) {
      var k = keyForOffset(i);
      var allDone = count > 0 && state.habits.every(function (h) {
        return isCompletedOn(h, k);
      });
      if (allDone) completedDays += 1;
    }
    els.weekSummary.innerHTML = "";
    var summary = document.createElement("span");
    if (count === 0) {
      summary.textContent = "Add habits to see your weekly progress.";
    } else {
      var strong = document.createElement("strong");
      strong.textContent = completedDays + " / 7";
      summary.appendChild(document.createTextNode("Perfect days this week: "));
      summary.appendChild(strong);
    }
    els.weekSummary.appendChild(summary);
  }

  function renderNotes() {
    var key = todayKey();
    els.notesInput.value = state.notes[key] || "";
    els.notesSaved.classList.remove("visible");
  }

  /* ---------- Actions ---------- */
  function addHabit(name) {
    var trimmed = name.trim();
    if (!trimmed) return;

    var habit = {
      id: "h_" + Date.now() + "_" + Math.floor(Math.random() * 10000),
      name: trimmed,
      createdAt: todayKey(),
      completions: []
    };

    state.habits.push(habit);
    saveHabits();
    render();
  }

  function toggleHabit(id, completed) {
    var habit = state.habits.find(function (h) { return h.id === id; });
    if (!habit) return;
    setCompletedOn(habit, todayKey(), completed);
    saveHabits();
    render();
  }

  function deleteHabit(id) {
    var habit = state.habits.find(function (h) { return h.id === id; });
    if (!habit) return;
    if (!window.confirm('Delete habit "' + habit.name + '" and all its history?')) return;
    state.habits = state.habits.filter(function (h) { return h.id !== id; });
    saveHabits();
    render();
  }

  function saveTodayNotes() {
    var key = todayKey();
    var value = els.notesInput.value;
    if (value) {
      state.notes[key] = value;
    } else {
      delete state.notes[key];
    }
    saveNotes();
  }

  /* ---------- Event wiring ---------- */
  els.form.addEventListener("submit", function (e) {
    e.preventDefault();
    addHabit(els.habitInput.value);
    els.habitInput.value = "";
    els.habitInput.focus();
  });

  els.habitList.addEventListener("change", function (e) {
    if (e.target.classList.contains("habit-check")) {
      toggleHabit(e.target.dataset.id, e.target.checked);
    }
  });

  els.habitList.addEventListener("click", function (e) {
    if (e.target.classList.contains("btn-danger")) {
      deleteHabit(e.target.dataset.id);
    }
  });

  var notesTimer = null;
  els.notesInput.addEventListener("input", function () {
    clearTimeout(notesTimer);
    notesTimer = setTimeout(function () {
      saveTodayNotes();
      els.notesSaved.classList.add("visible");
    }, 600);
  });

  /* ---------- Boot ---------- */
  render();
})();
