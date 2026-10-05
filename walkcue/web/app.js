const ask = document.getElementById("ask");
const result = document.getElementById("result");
const form = document.getElementById("form");
const areaInput = document.getElementById("area");
const go = document.getElementById("go");
const status = document.getElementById("status");
const reset = document.getElementById("reset");
const card = document.getElementById("card");
const storageKey = "walkcue-area";

function readSavedArea() {
  try {
    return localStorage.getItem(storageKey) || "";
  } catch {
    return "";
  }
}

function rememberArea(area) {
  try {
    localStorage.setItem(storageKey, area);
  } catch {
    /* The cue still shows if storage is blocked. */
  }
}

function showAsk(message) {
  result.hidden = true;
  ask.hidden = false;
  reset.hidden = true;
  card.setAttribute("aria-busy", "false");
  status.textContent = message || "";
  go.disabled = false;
  go.textContent = "Go walk";
  document.title = "Walk Cue";
}

function sourceLine(cue) {
  if (cue.notice) return cue.notice;
  if (cue.source === "model") {
    return cue.model ? `Cue from ${cue.model}` : "Cue from your model";
  }
  return "Offline cue";
}

function showResult(data) {
  ask.hidden = true;
  result.hidden = false;
  reset.hidden = false;
  card.setAttribute("aria-busy", "false");
  document.getElementById("minutes").textContent = String(data.cue.duration_minutes);
  document.getElementById("vibe").textContent = data.cue.vibe;
  document.getElementById("why").textContent = data.cue.why_now;
  document.getElementById("weather").textContent = data.weather.summary || "";
  const where = [data.area.label, data.weather.local_time].filter(Boolean);
  document.getElementById("where").textContent = where.join(" · ");

  const list = document.getElementById("spots");
  list.replaceChildren();
  const spots = Array.isArray(data.spots) ? data.spots : [];
  for (const spot of spots) {
    const item = document.createElement("li");
    const name = document.createElement("span");
    name.className = "spot-name";
    name.textContent = spot.name;
    const distance = document.createElement("span");
    distance.className = "spot-distance";
    distance.textContent = spot.distance;
    item.append(name, distance);
    list.append(item);
  }
  const label = document.getElementById("spots-label");
  const hasSpots = spots.length > 0;
  label.hidden = !hasSpots;
  list.hidden = !hasSpots;

  const note = document.getElementById("note");
  if (data.spots_note) {
    note.hidden = false;
    note.textContent = data.spots_note;
  } else {
    note.hidden = true;
    note.textContent = "";
  }
  document.getElementById("source").textContent = sourceLine(data.cue);
  document.title = `${data.cue.duration_minutes} min · Walk Cue`;
  result.focus();
}

function browserClock() {
  const now = new Date();
  const hour = String(now.getHours()).padStart(2, "0");
  const minute = String(now.getMinutes()).padStart(2, "0");
  return `${hour}:${minute}`;
}

async function requestCue(area) {
  go.disabled = true;
  go.textContent = "Checking outside…";
  status.textContent = "";
  card.setAttribute("aria-busy", "true");
  try {
    const response = await fetch("/api/cue", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Accept: "application/json",
      },
      body: JSON.stringify({ area, local_time: browserClock() }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = typeof payload.detail === "string"
        ? payload.detail
        : "That didn't work. Try the place again.";
      showAsk(detail);
      areaInput.focus();
      return;
    }
    rememberArea(area);
    showResult(payload);
  } catch {
    showAsk("The page couldn't reach Walk Cue. Try again.");
  }
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const area = areaInput.value.trim();
  if (!area) return;
  requestCue(area);
});

reset.addEventListener("click", () => {
  showAsk("");
  areaInput.focus();
  areaInput.select();
});

const saved = readSavedArea();
if (saved) {
  areaInput.value = saved;
  requestCue(saved);
}
