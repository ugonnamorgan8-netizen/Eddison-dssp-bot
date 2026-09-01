// DSSP Dashboard - Frontend Logic

function getCsrfToken() {
  const meta = document.querySelector('meta[name="csrf-token"]');
  return meta ? meta.content : "";
}

function postJSON(url, body = {}) {
  return fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-CSRFToken": getCsrfToken(),
    },
    body: JSON.stringify(body),
  });
}

let eventSource = null;
let isRunning = false;
let isScheduled = false;
let statusPollTimer = null;
let clockTimer = null;
let sseRetryTimer = null;

document.addEventListener("DOMContentLoaded", () => {
  updateClock();
  clockTimer = setInterval(updateClock, 1000);

  pollStatus();
  statusPollTimer = setInterval(() => {
    if (!document.hidden) pollStatus();
  }, 5000);

  // Allow the initial UI paint to complete before opening the live stream.
  setTimeout(() => {
    if (!document.hidden) startSSE();
  }, 150);

  const logoutForm = document.querySelector(".logout-form");
  if (logoutForm) {
    logoutForm.addEventListener("submit", stopRealtimeConnections);
  }
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    stopSSE();
    return;
  }
  pollStatus();
  startSSE();
});

window.addEventListener("pagehide", stopRealtimeConnections);

function updateClock() {
  const now = new Date();
  document.getElementById("clock").textContent =
    now.toLocaleTimeString("en-GB", { hour12: false });
  document.getElementById("date").textContent =
    now.toLocaleDateString("en-GB", {
      weekday: "short",
      day: "2-digit",
      month: "short",
      year: "numeric",
    });
}

async function pollStatus() {
  try {
    const res = await fetch("/status");
    const data = await res.json();

    isRunning = data.running;
    isScheduled = !!data.scheduled_at;

    const pill = document.getElementById("status-pill");
    const label = document.getElementById("pill-label");
    pill.className = "status-pill";

    if (data.running) {
      pill.classList.add("running");
      label.textContent = "Running";
    } else if (data.last_status === "done") {
      pill.classList.add("done");
      label.textContent = "Done";
    } else if (data.last_status === "error") {
      pill.classList.add("error");
      label.textContent = "Error";
    } else if (isScheduled) {
      pill.classList.add("scheduled");
      label.textContent = "Scheduled";
    } else {
      pill.classList.add("idle");
      label.textContent = "Idle";
    }

    const btn = document.getElementById("btn-run");
    const spinner = document.getElementById("run-spinner");
    btn.disabled = data.running;
    spinner.classList.toggle("hidden", !data.running);

    if (data.summary && Object.keys(data.summary).length) {
      document.getElementById("stat-updated").textContent = data.summary.updated ?? "-";
      document.getElementById("stat-skipped").textContent = data.summary.skipped ?? "-";
      document.getElementById("stat-failed").textContent = data.summary.failed ?? "-";
    }

    if (data.last_run) {
      const d = new Date(data.last_run);
      document.getElementById("last-run-time").textContent =
        "Last run: " +
        d.toLocaleDateString("en-GB", { day: "2-digit", month: "short" }) +
        " at " +
        d.toLocaleTimeString("en-GB", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
        });
    }

    updateScheduleCard(data);
  } catch (_) {
    // Ignore transient dashboard/network startup errors.
  }
}

function updateScheduleCard(data) {
  const empty = document.getElementById("schedule-empty");
  const info = document.getElementById("schedule-info");
  const net = document.getElementById("sched-net");

  if (data.scheduled_at) {
    empty.classList.add("hidden");
    info.classList.remove("hidden");
    document.getElementById("sched-time").textContent = data.scheduled_at;

    if (data.next_run) {
      const d = new Date(data.next_run);
      document.getElementById("sched-next").textContent =
        d.toLocaleDateString("en-GB", {
          weekday: "short",
          day: "2-digit",
          month: "short",
        }) +
        " " +
        d.toLocaleTimeString("en-GB", {
          hour12: false,
          hour: "2-digit",
          minute: "2-digit",
        });
    }

    if (net) {
      net.textContent = "Connected";
      net.className = "sched-value net-ok";
    }
  } else {
    empty.classList.remove("hidden");
    info.classList.add("hidden");
  }
}

function startSSE() {
  if (document.hidden) return;

  stopSSE();
  eventSource = new EventSource("/stream");

  eventSource.onmessage = (e) => {
    if (e.data) appendLog(e.data);
  };

  eventSource.onerror = () => {
    stopSSE();
    sseRetryTimer = setTimeout(() => {
      if (!document.hidden) startSSE();
    }, 3000);
  };
}

function stopSSE() {
  if (sseRetryTimer) {
    clearTimeout(sseRetryTimer);
    sseRetryTimer = null;
  }

  if (eventSource) {
    eventSource.close();
    eventSource = null;
  }
}

function stopRealtimeConnections() {
  stopSSE();

  if (statusPollTimer) {
    clearInterval(statusPollTimer);
    statusPollTimer = null;
  }

  if (clockTimer) {
    clearInterval(clockTimer);
    clockTimer = null;
  }
}

function classifyLine(line) {
  if (/\[DASHBOARD\]/.test(line)) return "log-dash";
  if (/\[SCHEDULER\]/.test(line)) return "log-dash";
  if (/SUMMARY/i.test(line)) return "log-summary";
  if (/Updated:|Done|success/i.test(line)) return "log-ok";
  if (/Error|Failed|FAIL/i.test(line)) return "log-fail";
  if (/Warn|Skip|Invalid/i.test(line)) return "log-warn";
  return "log-info";
}

function appendLog(line) {
  const consoleEl = document.getElementById("console");
  const placeholder = consoleEl.querySelector(".console-placeholder");
  if (placeholder) placeholder.remove();

  const span = document.createElement("span");
  span.className = "log-line " + classifyLine(line);
  span.textContent = line;
  consoleEl.appendChild(span);
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

function clearConsole() {
  const consoleEl = document.getElementById("console");
  consoleEl.innerHTML = '<span class="console-placeholder">Cleared. Waiting for output...</span>';
}

function scrollBottom() {
  const consoleEl = document.getElementById("console");
  consoleEl.scrollTop = consoleEl.scrollHeight;
}

async function runNow() {
  const btn = document.getElementById("btn-run");
  btn.disabled = true;
  clearConsole();

  try {
    const res = await postJSON("/run");
    const data = await res.json();
    if (!data.ok) {
      appendLog("[DASHBOARD ERROR] " + data.message);
      btn.disabled = false;
    }
  } catch (e) {
    appendLog("[DASHBOARD ERROR] Could not reach server: " + e);
    btn.disabled = false;
  }
}

function openScheduleModal() {
  document.getElementById("modal-overlay").classList.remove("hidden");
}

function closeScheduleModal() {
  document.getElementById("modal-overlay").classList.add("hidden");
}

async function saveSchedule() {
  const time = document.getElementById("time-input").value;
  closeScheduleModal();

  try {
    const res = await postJSON("/schedule", { time });
    const data = await res.json();
    if (data.ok) {
      appendLog(`[DASHBOARD] Schedule set: daily at ${time}`);
      pollStatus();
    } else {
      appendLog("[DASHBOARD ERROR] " + data.message);
    }
  } catch (e) {
    appendLog("[DASHBOARD ERROR] " + e);
  }
}

async function cancelSchedule() {
  try {
    const res = await postJSON("/cancel_schedule");
    const data = await res.json();
    if (data.ok) {
      appendLog("[DASHBOARD] Schedule cancelled.");
      pollStatus();
    }
  } catch (e) {
    appendLog("[DASHBOARD ERROR] " + e);
  }
}

async function loadLogList() {
  try {
    const res = await fetch("/logs");
    const files = await res.json();
    const list = document.getElementById("log-list");

    if (!files.length) {
      list.textContent = "No log files yet.";
      return;
    }

    list.innerHTML = "";
    files.forEach((file) => {
      const item = document.createElement("span");
      item.className = "log-item";
      item.textContent = file.replace("daily_update_", "").replace(".log", "");
      item.title = file;
      item.onclick = () => viewLog(file, item);
      list.appendChild(item);
    });
  } catch (_) {
    // Ignore log list fetch failures until the panel is opened again.
  }
}

async function viewLog(filename, el) {
  document.querySelectorAll(".log-item").forEach((item) => item.classList.remove("active"));
  el.classList.add("active");

  const viewer = document.getElementById("log-viewer");
  const content = document.getElementById("log-viewer-content");
  const title = document.getElementById("log-viewer-title");

  title.textContent = filename;
  content.textContent = "Loading...";
  viewer.classList.remove("hidden");

  try {
    const res = await fetch(`/logs/${filename}`);
    content.textContent = await res.text();
  } catch (e) {
    content.textContent = "Error loading log: " + e;
  }
}

function closeLogViewer() {
  document.getElementById("log-viewer").classList.add("hidden");
  document.querySelectorAll(".log-item").forEach((item) => item.classList.remove("active"));
}

function toggleLogHistory() {
  const card = document.getElementById("log-history-card");
  card.classList.toggle("hidden");

  if (!card.classList.contains("hidden")) {
    loadLogList();
  }
}
