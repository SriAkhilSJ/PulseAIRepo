/* ============================================================
   Consistency Tracker — app.js
   Vanilla JavaScript only. No frameworks, no dependencies.

   Features:
   - Add / delete work habits
   - Mark today's habits as completed (and undo)
   - Current & best streaks (overall + per habit)
   - Today's completion percentage
   - Weekly progress chart (last 7 days)
   - Daily notes with debounced autosave
   - localStorage persistence with graceful fallbacks for
     missing, corrupt, or blocked storage
   ============================================================ */

(function () {
  "use strict";

  /* ---------- Constants ---------- */
  var HABITS_KEY = "consistencyTracker.habits.v1";
  var NOTES_KEY = "consistencyTracker.notes.v1";
  var MAX_NAME_LENGTH = 60;
  var NOTES_SAVE_DELAY = 600; // ms
  var DELETE_CONFIRM_MS = 3000; // two-step delete window
  var MIDNIGHT_CHECK_MS = 60000; // re-render when the date rolls over

  var WEEKDAY_SHORT = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
  var WEEKDAY_LONG = [
    "Sunday", "Monday", "Tuesday", "Wednesday",
    "Thursday", "Friday", "Saturday"
  ];
  var MONTH_SHORT = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

  var DATE_KEY_RE = /^\d{4}-\d{2}-\d{2}$/;

  /* ---------- State ---------- */
  var state = {
    habits: [], // [{ id, name, createdAt, completions: { "YYYY-MM-DD": true } }]
    notes: {}   // { "YYYY-MM-DD": "note text" }
  };

  var els = {}; // DOM references, populated at boot
  var notesTimer = null;
  var lastDayKey = "";

  /* ============================================================
     Date helpers (local time — avoids UTC off-by-one bugs)
     ============================================================ */

  function pad2(n) {
    return n < 10 ? "0" + n : String(n);
  }

  function dateKey(d) {
    return d.getFullYear() + "-" + pad2(d.getMonth() + 1) + "-" + pad2(d.getDate());
  }

  function todayKey() {
    return dateKey(new Date());
  }

  function addDays(d, n) {
    var c = new Date(d);
    c.setDate(c.getDate() + n);
    return c;
  }

  function parseKey(key) {
    var parts = key.split("-");
    if (parts.length !== 3) return null;
    var dt = new Date(+parts[0], +parts[1] - 1, +parts[2]);
    return isNaN(dt.getTime()) ? null : dt;
  }

  function isNextDay(a, b) {
    var da = parseKey(a);
    if (!da) return false;
    return dateKey(addDays(da, 1)) === b;
  }

  /* ============================================================
     Storage — every access guarded with try/catch
     ============================================================ */

  function storageAvailable() {
    try {
      var testKey = "__consistency_tracker_test__";
      window.localStorage.setItem(testKey, "1");
      window.localStorage.removeItem(testKey);
      return true;
    } catch (e) {
      return false;
    }
  }

  function loadJSON(key) {
    try {
      var raw = window.localStorage.getItem(key);
      return raw === null ? null : JSON.parse(raw);
    } catch (e) {
      console.warn("[ConsistencyTracker] Could not read/parse '" + key + "', using defaults.", e);
      return null;
    }
  }

  function saveJSON(key, value) {
    try {
      window.localStorage.setItem(key, JSON.stringify(value));
      return true;
    } catch (e) {
      console.warn("[ConsistencyTracker] Could not save '" + key + "'.", e);
      return false;
    }
  }

  /* ---------- Data sanitization (corrupted / legacy data) ---------- */

  function sanitizeHabits(raw) {
    if (!Array.isArray(raw)) return [];
    var seen = {};
    var out = [];
    raw.forEach(function (h) {
      if (!h || typeof h !== "object") return;
      var name = typeof h.name === "string" ? h.name.trim() : "";
      if (!name || name.length > MAX_NAME_LENGTH) return;

      var id = typeof h.id === "string" && h.id ? h.id : uid();
      if (seen[id]) return;
      seen[id] = true;

      var completions = {};
      if (h.completions && typeof h.completions === "object" && !Array.isArray(h.completions)) {
        Object.keys(h.completions).forEach(function (k) {
          if (DATE_KEY_RE.test(k) && h.completions[k] === true) {
            completions[k] = true;
          }
        });
      }

      out.push({
        id: id,
        name: name,
        createdAt: typeof h.createdAt === "string" ? h.createdAt : new Date().toISOString(),
        completions: completions
      });
    });
    return out;
  }

  function sanitizeNotes(raw) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
    var out = {};
    Object.keys(raw).forEach(function (k) {
      if (DATE_KEY_RE.test(k) && typeof raw[k] === "string") {
        out[k] = raw[k];
      }
    });
    return out;
  }

  function uid() {
    return "h-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 8);
  }

  /* ============================================================
     Streak & completion math
     ============================================================ */

  function completionDates(habit) {
    return Object.keys(habit.completions).sort();
  }

  function isCompletedOn(habit, key) {
    return habit.completions[key] === true;
  }

  /* Longest run of consecutive dates in a sorted date-key array. */
  function longestRun(dates) {
    if (!dates.length) return 0;
    var best = 1;
    var cur = 1;
    for (var i = 1; i < dates.length; i++) {
      if (isNextDay(dates[i - 1], dates[i])) {
        cur += 1;
        if (cur > best) best = cur;
      } else {
        cur = 1;
      }
    }
    return best;
  }

  /* Current streak for one habit. If today isn't completed yet,
     the streak may continue from yesterday (grace period). */
  function currentStreakFor(habit) {
    var cursor = new Date();
    if (!isCompletedOn(habit, dateKey(cursor))) {
      cursor = addDays(cursor, -1);
    }
    var streak = 0;
    while (isCompletedOn(habit, dateKey(cursor))) {
      streak += 1;
      cursor = addDays(cursor, -1);
    }
    return streak;
  }

  function bestStreakFor(habit) {
    return longestRun(completionDates(habit));
  }

  function totalDaysFor(habit) {
    return completionDates(habit).length;
  }

  /* Union of every completion date across all habits. */
  function allCompletionDates() {
    var set = {};
    state.habits.forEach(function (h) {
      completionDates(h).forEach(function (k) { set[k] = true; });
    });
    return Object.keys(set).sort();
  }

  /* Overall current streak: consecutive days ending today (or
     yesterday, if today has no progress yet) with >=1 completion. */
  function overallCurrentStreak() {
    var set = {};
    allCompletionDates().forEach(function (k) { set[k] = true; });
    var cursor = new Date();
    if (!set[dateKey(cursor)]) {
      cursor = addDays(cursor, -1);
    }
    var streak = 0;
    while (set[dateKey(cursor)]) {
      streak += 1;
      cursor = addDays(cursor, -1);
    }
    return streak;
  }

  function overallBestStreak() {
    return longestRun(allCompletionDates());
  }

  function todayStats() {
    var total = state.habits.length;
    var done = 0;
    var key = todayKey();
    state.habits.forEach(function (h) {
      if (isCompletedOn(h, key)) done += 1;
    });
    var pct = total === 0 ? 0 : Math.round((done / total) * 100);
    return { total: total, done: done, pct: pct };
  }

  function completionPctFor(key) {
    var total = state.habits.length;
    if (total === 0) return 0;
    var done = 0;
    state.habits.forEach(function (h) {
      if (isCompletedOn(h, key)) done += 1;
    });
    return Math.round((done / total) * 100);
  }

  function lastSevenDays() {
    var days = [];
    var today = new Date();
    for (var i = 6; i >= 0; i--) {
      var d = addDays(today, -i);
      days.push({
        key: dateKey(d),
        label: i === 0 ? "Today" : WEEKDAY_SHORT[d.getDay()],
        isToday: i === 0
      });
    }
    return days;
  }

  function activeDaysLast7() {
    var set = {};
    allCompletionDates().forEach(function (k) { set[k] = true; });
    return lastSevenDays().filter(function (d) { return set[d.key]; }).length;
  }

  /* ============================================================
     Rendering
     ============================================================ */

  function renderTodayLabel() {
    var now = new Date();
    els.todayLabel.textContent =
      WEEKDAY_LONG[now.getDay()] + ", " +
      MONTH_SHORT[now.getMonth()] + " " + now.getDate() + ", " + now.getFullYear();
  }

  function plural(n, singular, pluralWord) {
    return n === 1 ? singular : pluralWord;
  }

  function renderStats() {
    var cur = overallCurrentStreak();
    var best = overallBestStreak();
    var ts = todayStats();
    var active = activeDaysLast7();

    els.statCurrentStreak.textContent = String(cur);
    els.statCurrentStreakSub.textContent =
      plural(cur, "day of progress in a row", "days of progress in a row");

    els.statBestStreak.textContent = String(best);
    els.statBestStreakSub.textContent = "your longest run ever";

    els.statTodayPercent.textContent = ts.pct + "%";
    els.statTodayPercentSub.textContent =
      ts.done + " of " + ts.total + plural(ts.total, " habit done", " habits done");

    els.statWeekActive.textContent = String(active);
    els.statWeekActiveSub.textContent =
      plural(active, "day with progress in last 7", "days with progress in last 7");
  }

  function renderWeekly() {
    var days = lastSevenDays();
    var fragment = document.createDocumentFragment();

    days.forEach(function (day) {
      var pct = completionPctFor(day.key);

      var col = document.createElement("div");
      col.className = "week-day" + (day.isToday ? " is-today" : "");

      var pctEl = document.createElement("span");
      pctEl.className = "week-pct";
      pctEl.textContent = pct + "%";

      var track = document.createElement("div");
      track.className = "week-bar-track";

      var bar = document.createElement("div");
      bar.className = "week-bar" + (pct === 0 ? " is-empty" : "");
      bar.style.height = pct + "%";
      bar.title = day.label + ": " + pct + "% of habits completed";

      track.appendChild(bar);

      var label = document.createElement("span");
      label.className = "week-label";
      label.textContent = day.label;

      col.appendChild(pctEl);
      col.appendChild(track);
      col.appendChild(label);
      fragment.appendChild(col);
    });

    els.weeklyChart.innerHTML = "";
    els.weeklyChart.appendChild(fragment);

    var active = activeDaysLast7();
    els.weeklyNote.textContent = active + " of 7 days with progress";
  }

  function renderHabits() {
    var hasHabits = state.habits.length > 0;
    els.emptyState.hidden = hasHabits;
    els.habitCount.textContent =
      state.habits.length === 0 ? "0 habits" :
      state.habits.length === 1 ? "1 habit" :
      state.habits.length + " habits";

    var fragment = document.createDocumentFragment();
    state.habits.forEach(function (habit) {
      fragment.appendChild(createHabitItem(habit));
    });

    els.habitList.innerHTML = "";
    els.habitList.appendChild(fragment);
  }

  function createHabitItem(habit) {
    var doneToday = isCompletedOn(habit, todayKey());

    var li = document.createElement("li");
    li.className = "habit-card" + (doneToday ? " is-done" : "");
    li.dataset.id = habit.id;

    /* ---- Info block ---- */
    var info = document.createElement("div");
    info.className = "habit-info";

    var name = document.createElement("p");
    name.className = "habit-name";
    name.textContent = habit.name;

    var meta = document.createElement("div");
    meta.className = "habit-meta";

    if (doneToday) {
      var doneChip = document.createElement("span");
      doneChip.className = "chip done-today";
      doneChip.textContent = "✓ Done today";
      meta.appendChild(doneChip);
    }

    var cur = currentStreakFor(habit);
    var streakChip = document.createElement("span");
    streakChip.className = "chip streak";
    streakChip.textContent = "🔥 " + cur + plural(cur, " day", " days");

    var bestChip = document.createElement("span");
    bestChip.className = "chip best";
    bestChip.textContent = "Best " + bestStreakFor(habit);

    var total = totalDaysFor(habit);
    var totalChip = document.createElement("span");
    totalChip.className = "chip";
    totalChip.textContent = total + plural(total, " day total", " days total");

    meta.appendChild(streakChip);
    meta.appendChild(bestChip);
    meta.appendChild(totalChip);

    info.appendChild(name);
    info.appendChild(meta);

    /* ---- Actions ---- */
    var actions = document.createElement("div");
    actions.className = "habit-actions";

    var toggle = document.createElement("button");
    toggle.type = "button";
    toggle.className = "toggle-btn" + (doneToday ? " is-done" : "");
    toggle.textContent = doneToday ? "Undo" : "Mark done";
    toggle.setAttribute("aria-pressed", doneToday ? "true" : "false");
    toggle.addEventListener("click", function () {
      toggleHabitToday(habit.id);
    });

    var del = document.createElement("button");
    del.type = "button";
    del.className = "delete-btn";
    del.textContent = "Delete";
    del.setAttribute("aria-label", "Delete habit " + habit.name);

    var confirmTimer = null;
    del.addEventListener("click", function () {
      if (del.classList.contains("is-confirming")) {
        removeHabit(habit.id);
        return;
      }
      del.classList.add("is-confirming");
      del.textContent = "Confirm?";
      clearTimeout(confirmTimer);
      confirmTimer = setTimeout(function () {
        del.classList.remove("is-confirming");
        del.textContent = "Delete";
      }, DELETE_CONFIRM_MS);
    });

    actions.appendChild(toggle);
    actions.appendChild(del);

    li.appendChild(info);
    li.appendChild(actions);
    return li;
  }

  function renderNotes() {
    els.notesTextarea.value = state.notes[todayKey()] || "";
    setNotesStatus("idle");
  }

  function setNotesStatus(mode) {
    var el = els.notesStatus;
    el.classList.remove("is-saving", "is-saved");
    if (mode === "saving") {
      el.textContent = "Saving…";
      el.classList.add("is-saving");
    } else if (mode === "saved") {
      el.textContent = "Saved ✓";
      el.classList.add("is-saved");
    } else {
      el.textContent = "Autosaved";
    }
  }

  /* ============================================================
     Actions
     ============================================================ */

  function findHabit(id) {
    for (var i = 0; i < state.habits.length; i++) {
      if (state.habits[i].id === id) return state.habits[i];
    }
    return null;
  }

  function toggleHabitToday(id) {
    var habit = findHabit(id);
    if (!habit) return;
    var key = todayKey();
    if (isCompletedOn(habit, key)) {
      delete habit.completions[key];
    } else {
      habit.completions[key] = true;
    }
    persistHabitsAndRender();
  }

  function removeHabit(id) {
    state.habits = state.habits.filter(function (h) { return h.id !== id; });
    persistHabitsAndRender();
  }

  function addHabit(name) {
    state.habits.push({
      id: uid(),
      name: name,
      createdAt: new Date().toISOString(),
      completions: {}
    });
    persistHabitsAndRender();
  }

  function persistHabitsAndRender() {
    var saved = saveJSON(HABITS_KEY, state.habits);
    if (!saved) showStorageWarning();
    renderStats();
    renderWeekly();
    renderHabits();
  }

  /* ============================================================
     Form validation
     ============================================================ */

  function validateName(raw, habits) {
    if (!raw) return "Please enter a habit name.";
    if (raw.length > MAX_NAME_LENGTH) {
      return "Keep the habit name under " + MAX_NAME_LENGTH + " characters.";
    }
    var duplicate = habits.some(function (h) {
      return h.name.toLowerCase() === raw.toLowerCase();
    });
    if (duplicate) {
      return "You already track \u201C" + raw + "\u201D \u2014 try a different habit.";
    }
    return null;
  }

  function handleAddSubmit(e) {
    e.preventDefault();
    var raw = els.habitInput.value.trim();
    var error = validateName(raw, state.habits);
    if (error) {
      showHabitError(error);
      els.habitInput.focus();
      return;
    }
    hideHabitError();
    addHabit(raw);
    els.habitInput.value = "";
    els.habitInput.focus();
  }

  function showHabitError(message) {
    els.habitError.textContent = message;
    els.habitError.hidden = false;
  }

  function hideHabitError() {
    els.habitError.hidden = true;
  }

  /* ============================================================
     Notes autosave (debounced)
     ============================================================ */

  function handleNotesInput() {
    var key = todayKey();
    var value = els.notesTextarea.value;
    if (value === "") {
      delete state.notes[key];
    } else {
      state.notes[key] = value;
    }
    setNotesStatus("saving");
    clearTimeout(notesTimer);
    notesTimer = setTimeout(function () {
      var saved = saveJSON(NOTES_KEY, state.notes);
      if (!saved) showStorageWarning();
      setNotesStatus(saved ? "saved" : "idle");
    }, NOTES_SAVE_DELAY);
  }

  /* ============================================================
     Boot
     ============================================================ */

  function showStorageWarning() {
    els.storageWarning.hidden = false;
  }

  function render() {
    renderTodayLabel();
    renderStats();
    renderWeekly();
    renderHabits();
    renderNotes();
  }

  function boot() {
    els = {
      todayLabel: document.getElementById("today-label"),
      storageWarning: document.getElementById("storage-warning"),
      statCurrentStreak: document.getElementById("stat-current-streak"),
      statCurrentStreakSub: document.getElementById("stat-current-streak-sub"),
      statBestStreak: document.getElementById("stat-best-streak"),
      statBestStreakSub: document.getElementById("stat-best-streak-sub"),
      statTodayPercent: document.getElementById("stat-today-percent"),
      statTodayPercentSub: document.getElementById("stat-today-percent-sub"),
      statWeekActive: document.getElementById("stat-week-active"),
      statWeekActiveSub: document.getElementById("stat-week-active-sub"),
      weeklyChart: document.getElementById("weekly-chart"),
      weeklyNote: document.getElementById("weekly-note"),
      habitForm: document.getElementById("habit-form"),
      habitInput: document.getElementById("habit-input"),
      habitError: document.getElementById("habit-error"),
      habitList: document.getElementById("habit-list"),
      habitCount: document.getElementById("habit-count"),
      emptyState: document.getElementById("empty-state"),
      notesTextarea: document.getElementById("notes-textarea"),
      notesStatus: document.getElementById("notes-status")
    };

    // Warn early if the browser blocks storage entirely.
    if (!storageAvailable()) showStorageWarning();

    // Load + sanitize. Corrupt or missing data falls back to defaults.
    state.habits = sanitizeHabits(loadJSON(HABITS_KEY));
    state.notes = sanitizeNotes(loadJSON(NOTES_KEY));

    els.habitForm.addEventListener("submit", handleAddSubmit);
    els.habitInput.addEventListener("input", function () {
      if (!els.habitError.hidden) hideHabitError();
    });
    els.notesTextarea.addEventListener("input", handleNotesInput);

    lastDayKey = todayKey();
    render();

    // Re-render if the app stays open across midnight.
    setInterval(function () {
      var nowKey = todayKey();
      if (nowKey !== lastDayKey) {
        lastDayKey = nowKey;
        render();
      }
    }, MIDNIGHT_CHECK_MS);

    console.info("[ConsistencyTracker] Booted with " + state.habits.length + " habit(s).");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", boot);
  } else {
    boot();
  }
})();
