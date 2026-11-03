const topbar = document.querySelector(".topbar");

new ResizeObserver(() =>
  document.documentElement.style.setProperty(
    "--topbar-height",
    topbar.getBoundingClientRect().height + "px",
  )
).observe(topbar);

const modeToggle = document.getElementById("mode-toggle");
let modePending = false;

async function updateMode() {
  try {
    const response = await fetch("/api/mode", { cache: "no-store" });
    if (!response.ok) throw Error();
    const data = await response.json();
    const previous = document.documentElement.dataset.mode;
    document.documentElement.dataset.mode =
      ["AUTO", "MANUAL"].includes(data.mode) ? data.mode : "";
    if (previous !== document.documentElement.dataset.mode) {
      window.dispatchEvent(new Event("modechange"));
    }
    modeToggle.checked = data.mode === "AUTO";
    modeToggle.disabled = modePending || !document.documentElement.dataset.mode;
    document.getElementById("mode").textContent = data.mode ||
      "Nicht verfügbar";
    document.getElementById("mode-status").textContent = data.mode
      ? ""
      : "Verbindung zum Sensorprozess fehlt";
    return data.mode;
  } catch (e) {
    document.documentElement.dataset.mode = "";
    window.dispatchEvent(new Event("modechange"));
    modeToggle.disabled = true;
    document.getElementById("mode").textContent = "Nicht verfügbar";
    document.getElementById("mode-status").textContent =
      "Verbindung zum Dashboard fehlt";
    return null;
  }
}
modeToggle.addEventListener("change", async () => {
  const target = modeToggle.checked ? "AUTO" : "MANUAL";
  modeToggle.checked = document.documentElement.dataset.mode === "AUTO";
  modePending = true;
  modeToggle.disabled = true;
  try {
    const response = await fetch("/api/mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode: target }),
    });
    if (!response.ok) throw Error();
    let confirmed = false;
    for (let i = 0; i < 20; i++) {
      await new Promise((resolve) => setTimeout(resolve, 250));
      if (await updateMode() === target) {
        confirmed = true;
        break;
      }
    }
    if (!confirmed) throw Error();
  } catch (e) {
    document.getElementById("mode-status").textContent =
      "Moduswechsel nicht möglich";
  } finally {
    modePending = false;
    modeToggle.disabled = !["AUTO", "MANUAL"].includes(
      document.documentElement.dataset.mode,
    );
  }
});
updateMode();
setInterval(updateMode, 1000);

const actuatorPanel = document.getElementById("actuator-panel"),
  actuatorError = document.getElementById("actuator-error");

let actuatorGeneration = 0, actuatorBusy = false;

function actuatorVisible() {
  return ["AUTO", "MANUAL"].includes(document.documentElement.dataset.mode);
}
function actuatorEditable() {
  return document.documentElement.dataset.mode === "MANUAL";
}
function applyActuators(values) {
  for (const device of ["fan", "led"]) {
    document.getElementById("auto-" + device).textContent = values[device] +
      " %";
    const input = document.getElementById(device + "-control");
    if (!input.matches(":active")) {
      input.value = values[device];
      document.getElementById(device + "-value").textContent = values[device] +
        " %";
    }
    input.disabled = !actuatorEditable();
  }
}
async function updateActuators() {
  if (!actuatorVisible() || actuatorBusy) return;
  const generation = actuatorGeneration;
  try {
    const response = await fetch("/api/actuators", { cache: "no-store" });
    if (!response.ok) throw Error();
    const values = await response.json();
    if (
      generation !== actuatorGeneration || !actuatorVisible() || actuatorBusy
    ) return;
    applyActuators(values);
    if (actuatorError.textContent === "Steuerung nicht erreichbar") {
      actuatorError.textContent = "";
    }
  } catch (e) {
    if (generation === actuatorGeneration && actuatorVisible()) {
      for (const device of ["fan", "led"]) {
        document.getElementById(device + "-control").disabled = true;
      }
      actuatorError.textContent = "Steuerung nicht erreichbar";
    }
  }
}
function syncActuatorMode() {
  actuatorGeneration++;
  actuatorPanel.hidden = !actuatorVisible();
  document.getElementById("auto-actuators").hidden =
    document.documentElement.dataset.mode !== "AUTO";
  document.getElementById("manual-actuators").hidden = !actuatorEditable();
  for (const device of ["fan", "led"]) {
    document.getElementById(device + "-control").disabled = true;
  }
  if (!actuatorPanel.hidden) updateActuators();
}
function renderThermal(state) {
  const marker = document.getElementById("thermal-marker");
  document.getElementById("thermal-value").textContent = "Max. Temp: " +
    (state && state.temperature !== null
      ? state.temperature.toFixed(1).replace(".", ",") + " °C"
      : "–");
  marker.hidden = !state || state.temperature === null;
  if (!state) return;
  const low = state.target - 2, span = state.maximum - low;
  marker.style.left =
    Math.max(0, Math.min(100, (state.temperature - low) / span * 100)) + "%";
  document.querySelector(".thermal-target").style.left =
    ((state.target - low) / span * 100) + "%";
  document.getElementById("thermal-low").textContent = low + " °C";
  document.getElementById("thermal-target").textContent = "Ziel " +
    state.target + " °C";
  document.getElementById("thermal-max").textContent = "Max. " + state.maximum +
    " °C";
  document.getElementById("thermal-bar").setAttribute(
    "aria-label",
    "Wärmere Seite " + (state.temperature ?? "unbekannt") + " °C, Ziel " +
      state.target + " °C, Maximum " + state.maximum + " °C",
  );
}
async function updateLightSchedule() {
  if (document.documentElement.dataset.mode !== "AUTO") return;
  try {
    const response = await fetch("/api/automatic/light", { cache: "no-store" });
    if (!response.ok) throw Error();
    const plan = await response.json();
    if (document.documentElement.dataset.mode !== "AUTO") return;
    renderThermal(plan.thermal);
    const fmt = (m) =>
        String(Math.floor(m / 60)).padStart(2, "0") + ":" +
        String(m % 60).padStart(2, "0"),
      end = (plan.start + plan.duration) % 1440;
    document.getElementById("light-hours").textContent = "Zeitplan: " +
      fmt(plan.start) + "–" + fmt(end);
    const bar = document.getElementById("light-timeline");
    bar.replaceChildren();
    for (
      const [start, finish] of (plan.start + plan.duration <= 1440
        ? [[plan.start, plan.start + plan.duration]]
        : [[plan.start, 1440], [0, end]])
    ) {
      const segment = document.createElement("span");
      segment.className = "auto-light-segment";
      segment.style.left = (start / 1440 * 100) + "%";
      segment.style.width = ((finish - start) / 1440 * 100) + "%";
      bar.appendChild(segment);
    }
    const marker = document.createElement("span");
    marker.className = "auto-now";
    marker.style.left = (plan.current / 1440 * 100) + "%";
    bar.appendChild(marker);
    bar.setAttribute(
      "aria-label",
      "Lichtphase " + fmt(plan.start) + " bis " + fmt(end) + ", aktuell " +
        fmt(plan.current),
    );
  } catch (e) {
    renderThermal(null);
    document.getElementById("light-hours").textContent = "Zeitplan: –";
    document.getElementById("light-timeline").replaceChildren();
  }
}
window.addEventListener("modechange", () => {
  syncActuatorMode();
  updateLightSchedule();
});
setInterval(() => {
  syncActuatorVisibility();
  updateActuators();
  updateLightSchedule();
}, 1000);

function syncActuatorVisibility() {
  if (actuatorPanel.hidden === actuatorVisible()) syncActuatorMode();
}
for (const device of ["fan", "led"]) {
  const input = document.getElementById(device + "-control");
  input.addEventListener(
    "input",
    () =>
      document.getElementById(device + "-value").textContent = input.value +
        " %",
  );
  input.addEventListener("change", async () => {
    actuatorBusy = true;
    try {
      const response = await fetch("/api/actuators/" + device, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ value: Number(input.value) }),
      });
      if (!response.ok) throw Error(await response.text());
      if (actuatorVisible()) applyActuators(await response.json());
      actuatorError.textContent = "";
    } catch (e) {
      actuatorError.textContent = e.message || "Steuerung nicht erreichbar";
    } finally {
      actuatorBusy = false;
      updateActuators();
    }
  });
}
const chartColors = {
  temperature: "#d97706",
  humidity: "#0891b2",
  co2: "#7c3aed",
  light: "#ca8a04",
};

function setReading(id, text, averaged = false) {
  const el = document.getElementById(id);
  el.textContent = text;
  el.classList.toggle("averaged", averaged);
}
function initMetric(metric, unit) {
  const periodSelect = document.getElementById("global-period"),
    chart = document.getElementById(metric + "-chart");

  let chartRequest = 0;

  function drawMetricChart(data) {
    chart.replaceChildren();
    const historyPoints = data.points.filter((p) =>
      p.value !== null && Number.isFinite(p.value)
    );
    const points = historyPoints;

    const status = document.getElementById(metric + "-chart-status");
    if (!points.length) {
      status.textContent = "Keine Messwerte im gewählten Zeitraum";
      return;
    }
    status.textContent = "";

    const ns = "http://www.w3.org/2000/svg",
      width = 800,
      height = 230,
      left = 55,
      right = 20,
      top = 15,
      bottom = 35;

    chart.setAttribute("viewBox", `0 0 ${width} ${height}`);

    const span = {
        "10m": 600,
        "1h": 3600,
        "24h": 86400,
        "7d": 604800,
        "30d": 2592000,
      }[periodSelect.value],
      end = Date.now() / 1000,
      start = end - span;

    let low = Math.min(...points.map((p) => p.value)),
      high = Math.max(...points.map((p) => p.value));
    const pad = Math.max((high - low) * .1, .5);
    low -= pad;
    high += pad;

    function element(name, attributes) {
      const el = document.createElementNS(ns, name);
      for (const [key, value] of Object.entries(attributes)) {
        el.setAttribute(key, value);
      }
      chart.appendChild(el);
      return el;
    }
    const x = (t) => left + (t - start) / span * (width - left - right),
      y = (v) => top + (high - v) / (high - low) * (height - top - bottom);

    for (let i = 0; i < 3; i++) {
      const v = low + (high - low) * i / 2, yy = y(v);
      element("line", {
        x1: left,
        x2: width - right,
        y1: yy,
        y2: yy,
        stroke: "var(--grid)",
      });
      const label = element("text", { x: 0, y: yy + 4 });
      label.textContent = v.toLocaleString("de-DE", {
        minimumFractionDigits: 1,
        maximumFractionDigits: 1,
      }) + " " + unit;
    }
    let path = "", previous = null;
    for (const point of points) {
      const px = x(point.time);
      if (px < left || px > width - right) continue;
      path +=
        (previous === null || point.time - previous > data.window_seconds * 1.5
          ? "M"
          : "L") + px + " " + y(point.value) + " ";
      previous = point.time;
    }
    element("path", {
      d: path,
      fill: "none",
      stroke: chartColors[metric],
      "stroke-width": "2",
      "stroke-linejoin": "round",
      "stroke-linecap": "round",
      "vector-effect": "non-scaling-stroke",
    });
    for (const point of historyPoints) {
      const px = x(point.time);
      if (px < left || px > width - right) continue;
      const circle = element("circle", {
          cx: px,
          cy: y(point.value),
          r: 4,
          fill: chartColors[metric],
          class: "chart-point",
        }),
        title = document.createElementNS(ns, "title");
      title.textContent = new Date(point.time * 1000).toLocaleString("de-DE") +
        " · " + point.value.toFixed(1) + " " + unit + " · " + point.source;
      circle.appendChild(title);
    }
    const tickStep = {
      "10m": 120,
      "1h": 600,
      "24h": 14400,
      "7d": 86400,
      "30d": 432000,
    }[periodSelect.value];

    element("line", {
      x1: left,
      x2: width - right,
      y1: height - bottom,
      y2: height - bottom,
      stroke: "var(--border)",
    });

    for (
      let time = Math.ceil(start / tickStep) * tickStep;
      time <= end;
      time += tickStep
    ) {
      const xx = x(time);
      element("line", {
        x1: xx,
        x2: xx,
        y1: top,
        y2: height - bottom + 5,
        stroke: "var(--grid)",
      });

      const label = element("text", {
        x: xx,
        y: height - 12,
        "text-anchor": "middle",
      });

      const options = ["10m", "1h"].includes(periodSelect.value)
        ? { hour: "2-digit", minute: "2-digit" }
        : periodSelect.value === "24h"
        ? {
          day: "2-digit",
          month: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        }
        : { day: "2-digit", month: "2-digit" };

      label.textContent = new Date(time * 1000).toLocaleString(
        "de-DE",
        options,
      );
    }
  }
  async function updateMetricHistory() {
    const request = ++chartRequest;
    try {
      const response = await fetch(
        "/api/" + metric + "?period=" + periodSelect.value,
        { cache: "no-store" },
      );
      if (!response.ok) throw Error();
      const data = await response.json();
      if (request !== chartRequest) return;
      drawMetricChart(data);
    } catch (e) {
      if (request !== chartRequest) return;
      chart.replaceChildren();
      document.getElementById(metric + "-chart-status").textContent =
        "Verlauf nicht erreichbar";
    }
  }
  async function updateCurrentMetric() {
    try {
      const response = await fetch("/api/" + metric + "?current_only=true", {
        cache: "no-store",
      });
      if (!response.ok) throw Error();
      const data = await response.json();
      setReading(
        metric,
        data.current.value === null
          ? "–"
          : data.current.value.toLocaleString("de-DE", {
            minimumFractionDigits: 1,
            maximumFractionDigits: 1,
          }) + " " + unit,
        data.current.averaged === true,
      );
      document.getElementById(metric + "-source").textContent =
        data.current.source;
    } catch (e) {
      setReading(metric, "–");
      document.getElementById(metric + "-source").textContent =
        "Daten nicht erreichbar";
    }
  }
  periodSelect.addEventListener("change", updateMetricHistory);
  window.addEventListener("modechange", updateMetricHistory);
  updateMetricHistory();
  updateCurrentMetric();
  setInterval(updateMetricHistory, 30000);
  setInterval(updateCurrentMetric, 2000);
}
initMetric("temperature", "°C");
initMetric("humidity", "%");
initMetric("co2", "ppm");
initMetric("light", "lx");

function initUltrasonicChart() {
  const chart = document.getElementById("ultrasonic-chart");
  const status = document.getElementById("ultrasonic-status");
  const period = document.getElementById("global-period");
  const colors = {
    tank: "#2563eb",
    moss1: "#15803d",
    moss2: "#d97706",
    moss3: "#7c3aed",
    moss4: "#dc2626",
  };
  const spans = {
    "10m": 600,
    "1h": 3600,
    "24h": 86400,
    "7d": 604800,
    "30d": 2592000,
  };
  let request = 0;

  async function update() {
    const current = ++request;
    try {
      const response = await fetch("/api/ultrasonic?period=" + period.value, {
        cache: "no-store",
      });
      if (!response.ok) throw Error();
      const data = await response.json();
      if (current !== request) return;
      chart.replaceChildren();
      const end = Date.now() / 1000,
        span = spans[period.value],
        start = end - span;
      const series = Object.fromEntries(
        Object.keys(colors).map(
          (side) => [
            side,
            (data.series[side] || []).filter((point) =>
              Number.isFinite(point.time) && Number.isFinite(point.value) &&
              point.time >= start && point.time <= end
            ),
          ],
        ),
      );
      const points = Object.values(series).flat();
      if (!points.length) {
        status.textContent = "Keine berechneten Höhen im gewählten Zeitraum";
        return;
      }
      status.textContent = "";
      let low = Math.min(...points.map((point) => point.value)),
        high = Math.max(...points.map((point) => point.value));
      const padding = Math.max((high - low) * .1, .5);
      low -= padding;
      high += padding;
      const ns = "http://www.w3.org/2000/svg",
        left = 55,
        right = 780,
        top = 15,
        bottom = 195;
      const x = (time) => left + (time - start) / span * (right - left);
      const y = (value) => top + (high - value) / (high - low) * (bottom - top);
      function add(name, attrs) {
        const element = document.createElementNS(ns, name);
        for (const [key, value] of Object.entries(attrs)) {
          element.setAttribute(key, value);
        }
        chart.appendChild(element);
        return element;
      }
      for (const value of [low, (low + high) / 2, high]) {
        const label = add("text", { x: 0, y: y(value) + 4 });
        label.textContent =
          value.toLocaleString("de-DE", { maximumFractionDigits: 1 }) + " cm";
      }
      for (const [side, values] of Object.entries(series)) {
        let path = "", previous = null;
        for (const point of values) {
          const gap = previous === null ||
            point.time - previous > Math.max(12, data.window_seconds * 1.5);
          path += (gap ? "M" : "L") + x(point.time) + " " + y(point.value) +
            " ";
          previous = point.time;
        }
        if (path) {
          add("path", {
            d: path,
            fill: "none",
            stroke: colors[side],
            "stroke-width": 2,
            "stroke-linejoin": "round",
            "stroke-linecap": "round",
            "vector-effect": "non-scaling-stroke",
          });
        }
      }
      for (const [time, anchor] of [[start, "start"], [end, "end"]]) {
        const label = add("text", {
          x: x(time),
          y: 224,
          "text-anchor": anchor,
        });
        label.textContent = new Date(time * 1000).toLocaleString("de-DE", {
          day: "2-digit",
          month: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
        });
      }
    } catch (error) {
      if (current !== request) return;
      chart.replaceChildren();
      status.textContent = "Verlauf nicht erreichbar";
    }
  }
  period.addEventListener("change", update);
  update();
  setInterval(update, 30000);
}
initUltrasonicChart();

const debugToggle = document.getElementById("debug-toggle"),
  debugPanel = document.getElementById("debug-panel"),
  debugStatus = document.getElementById("debug-status");

async function updateDebug() {
  if (!debugToggle.checked) return;
  try {
    const response = await fetch("/api/debug/sensors", { cache: "no-store" });
    if (!response.ok) throw Error();
    const data = await response.json();
    if (!debugToggle.checked) return;
    debugPanel.querySelectorAll("tbody [id]").forEach((cell) =>
      cell.textContent = "–"
    );
    for (const reading of data.readings) {
      const cell = document.getElementById(
        `${reading.side}-${reading.sensor}-${reading.field}`,
      );
      if (cell) cell.textContent = String(reading.value);
    }
    const fmt = (value) =>
      Number.isFinite(value)
        ? value.toLocaleString("de-DE", {
          minimumFractionDigits: 2,
          maximumFractionDigits: 3,
        })
        : "–";
    for (const [side, values] of Object.entries(data.ultrasonic)) {
      for (const [field, value] of Object.entries(values)) {
        const column = {
          raw_cm: "raw",
          filtered_cm: "filtered",
          inlier_percent: "inliers",
          calculated_cm: "calculated",
        }[field];
        const cell = document.getElementById(`ultrasonic-${side}-${column}`);
        if (cell) cell.textContent = column === "inliers"
          ? Number.isFinite(value)
            ? value.toLocaleString("de-DE", { maximumFractionDigits: 1 }) + " %"
            : "–"
          : fmt(value);
      }
      if (values.raw_cm === null) {
        const cell = document.getElementById(`ultrasonic-${side}-raw`);
        const status = data.ultrasonic_status?.[side];
        if (cell) {
          cell.textContent = status === "invalid"
            ? "Kein gültiger Messwert"
            : "Kein aktueller Messwert";
        }
      }
    }
    const filter = data.filter;
    document.getElementById("ultrasonic-filter-note").textContent =
      `${filter.samples} Messungen; nur Werte innerhalb ±${
        fmt(filter.water_spread_cm)
      } cm (Wasser) bzw. ±${
        fmt(filter.moss_spread_cm)
      } cm (Moos) um den Median fließen in den geglätteten Abstand ein. Die Prozentzahl zeigt ihren Anteil an den ${filter.samples} Messungen. Bei fehlendem Echo oder mehr als ${filter.max_gap_seconds} s Messpause beginnt der Filter neu.`;
    document.getElementById("ultrasonic-height-note").textContent =
      `Höhe ab Tankboden = Montagehöhe − geglätteter Abstand; Wassertiefe mindestens 0. Montagehöhen (cm): Wasser ${
        fmt(data.water_floor_distance_cm)
      } · Moos ${fmt(data.moss_mounting_height_cm)}.`;
    debugStatus.textContent = data.readings.length
      ? ""
      : "Keine aktuellen Messwerte";
  } catch (e) {
    if (debugToggle.checked) {
      debugPanel.querySelectorAll("tbody [id]").forEach((cell) =>
        cell.textContent = "–"
      );
      debugStatus.textContent = "Sensordaten nicht erreichbar";
    }
  }
}
debugToggle.addEventListener("change", () => {
  debugPanel.hidden = !debugToggle.checked;
  if (debugToggle.checked) updateDebug();
});
setInterval(updateDebug, 1000);

const camera = document.getElementById("camera");
function connectCamera() {
  camera.src = "/camera/stream.mjpg?" + Date.now();
}
camera.onload = () =>
  document.getElementById("camera-status").textContent = "Live Feed";
camera.onerror = () => {
  document.getElementById("camera-status").textContent =
    "Live Feed: Nicht erreichbar";
  setTimeout(connectCamera, 3000);
};
connectCamera();
