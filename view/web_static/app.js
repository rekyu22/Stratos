const MAX_POINTS = 20000;
const WS_PERIOD_MS = 250;

let liveSocket = null;
let replayMode = false;
let wsFailures = 0;
let pollingTimer = null;
let modeOverrideOnce = null;
let sampleBuffer = [];
let lastFrameId = null;
let gyroBias = { gyr_x: 0, gyr_y: 0, gyr_z: 0 };

function fmt(value, decimals = 3, unit = "") {
  if (value === null || value === undefined || !Number.isFinite(value)) {
    return "N/A";
  }
  return `${Number(value).toFixed(decimals)}${unit}`;
}

function setText(id, value) {
  const el = document.getElementById(id);
  if (el) {
    el.textContent = value;
  }
}

function levelClass(level) {
  if (level === "good") {
    return "health good";
  }
  if (level === "warn") {
    return "health warn";
  }
  return "health bad";
}

function setHealth(id, label, value, level) {
  const el = document.getElementById(id);
  if (!el) {
    return;
  }
  el.className = levelClass(level);
  el.textContent = `${label}: ${value}`;
}

function decimalsForSpan(span) {
  if (span >= 100) {
    return 0;
  }
  if (span >= 10) {
    return 1;
  }
  if (span >= 1) {
    return 2;
  }
  if (span >= 0.1) {
    return 3;
  }
  if (span >= 0.01) {
    return 4;
  }
  return 5;
}

function minSpanForUnit(unit) {
  if (unit === "V") {
    return 0.002;
  }
  if (unit === "m") {
    return 0.05;
  }
  if (unit === "hPa") {
    return 0.02;
  }
  if (unit === "°/s") {
    return 1.0;
  }
  if (unit === "°") {
    return 2.0;
  }
  return 0.1;
}

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value));
}

function toTimestampMs(sample) {
  const value = Date.parse((sample && sample.timestamp) || "");
  return Number.isFinite(value) ? value : null;
}

function calibrateSample(sample) {
  if (!sample) {
    return sample;
  }
  return {
    ...sample,
    gyr_x: Number.isFinite(sample.gyr_x) ? sample.gyr_x - gyroBias.gyr_x : sample.gyr_x,
    gyr_y: Number.isFinite(sample.gyr_y) ? sample.gyr_y - gyroBias.gyr_y : sample.gyr_y,
    gyr_z: Number.isFinite(sample.gyr_z) ? sample.gyr_z - gyroBias.gyr_z : sample.gyr_z,
  };
}

function calibratedSamples(samples) {
  return (samples || []).map((sample) => calibrateSample(sample));
}

function tareGyro() {
  const valid = sampleBuffer
    .filter(
      (sample) =>
        Number.isFinite(sample.gyr_x) &&
        Number.isFinite(sample.gyr_y) &&
        Number.isFinite(sample.gyr_z)
    )
    .slice(-20);

  if (valid.length === 0) {
    return "Tarage gyro impossible: aucune trame gyro";
  }

  gyroBias = {
    gyr_x: valid.reduce((sum, sample) => sum + sample.gyr_x, 0) / valid.length,
    gyr_y: valid.reduce((sum, sample) => sum + sample.gyr_y, 0) / valid.length,
    gyr_z: valid.reduce((sum, sample) => sum + sample.gyr_z, 0) / valid.length,
  };
  return `Gyro tare: X ${gyroBias.gyr_x.toFixed(2)} / Y ${gyroBias.gyr_y.toFixed(2)} / Z ${gyroBias.gyr_z.toFixed(2)} °/s`;
}

function drawNoData(ctx, left, top) {
  ctx.fillStyle = "rgba(186, 203, 224, 0.75)";
  ctx.font = "11px Segoe UI, sans-serif";
  ctx.fillText("No data", left + 8, top + 14);
}

function drawMultiSeries(canvasId, samples, seriesDefs, unit) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const left = 56;
  const right = 10;
  const top = 10;
  const bottom = 24;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;

  const flattened = [];
  for (const def of seriesDefs) {
    for (const sample of samples || []) {
      const value = sample[def.field];
      if (value !== null && value !== undefined && Number.isFinite(value)) {
        flattened.push(value);
      }
    }
  }

  if (flattened.length === 0 || (samples || []).length < 2) {
    drawNoData(ctx, left, top);
    return;
  }

  let min = Math.min(...flattened);
  let max = Math.max(...flattened);
  if (min === max) {
    const half = minSpanForUnit(unit) / 2.0;
    min -= half;
    max += half;
  } else {
    const span = max - min;
    const minSpan = minSpanForUnit(unit);
    if (span < minSpan) {
      const mid = (min + max) / 2.0;
      min = mid - minSpan / 2.0;
      max = mid + minSpan / 2.0;
    }
  }

  const pad = (max - min) * 0.12;
  min -= pad;
  max += pad;
  const range = max - min;
  const decimals = decimalsForSpan(range);

  ctx.fillStyle = "rgba(186, 203, 224, 0.75)";
  ctx.font = "11px Segoe UI, sans-serif";
  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;

  const yTicks = 5;
  for (let i = 0; i < yTicks; i += 1) {
    const ratio = i / (yTicks - 1);
    const y = top + ratio * plotHeight;
    const value = max - ratio * (max - min);
    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotWidth, y);
    ctx.stroke();
    ctx.fillText(`${value.toFixed(decimals)} ${unit}`, 2, y + 3);
  }

  const xTicks = 5;
  const timestamps = (samples || []).map((s) => toTimestampMs(s));
  const validTs = timestamps.filter((t) => t !== null);
  const tMin = validTs.length ? Math.min(...validTs) : 0;
  const tMax = validTs.length ? Math.max(...validTs) : 1;
  const fallbackDurationMs = Math.max(((samples || []).length - 1) * WS_PERIOD_MS, 1);

  for (let i = 0; i < xTicks; i += 1) {
    const ratio = i / (xTicks - 1);
    const x = left + ratio * plotWidth;
    let sec = 0.0;
    if (validTs.length >= 2 && tMax > tMin) {
      const t = tMin + ratio * (tMax - tMin);
      sec = (t - tMax) / 1000.0;
    } else {
      sec = -((1 - ratio) * fallbackDurationMs) / 1000.0;
    }
    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();
    ctx.fillText(`${sec.toFixed(1)}s`, x - 12, top + plotHeight + 14);
  }

  ctx.strokeStyle = "rgba(255,255,255,0.25)";
  ctx.beginPath();
  ctx.rect(left, top, plotWidth, plotHeight);
  ctx.stroke();

  for (const def of seriesDefs) {
    ctx.strokeStyle = def.color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    let penDown = false;
    (samples || []).forEach((sample, idx) => {
      const value = sample[def.field];
      if (value === null || value === undefined || !Number.isFinite(value)) {
        penDown = false;
        return;
      }
      const x = left + (idx / Math.max((samples || []).length - 1, 1)) * plotWidth;
      const y = top + (1 - (value - min) / (max - min)) * plotHeight;
      if (!penDown) {
        ctx.moveTo(x, y);
        penDown = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.stroke();
  }

  let legendX = left + 8;
  const legendY = top + 12;
  for (const def of seriesDefs) {
    ctx.fillStyle = def.color;
    ctx.fillRect(legendX, legendY - 8, 8, 8);
    ctx.fillStyle = "rgba(210,224,242,0.95)";
    ctx.fillText(def.name, legendX + 12, legendY);
    legendX += 64;
  }
}

function drawSeries(canvasId, samples, field, color, unit) {
  drawMultiSeries(canvasId, samples, [{ name: "value", field, color }], unit);
}

function drawTrajectory(canvasId, samples, xField, yField, unit) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    return;
  }

  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const left = 46;
  const right = 12;
  const top = 14;
  const bottom = 30;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;

  const points = (samples || [])
    .map((sample) => ({ x: sample[xField], y: sample[yField] }))
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));

  if (points.length < 2) {
    drawNoData(ctx, left, top);
    return;
  }

  const xs = points.map((point) => point.x);
  const ys = points.map((point) => point.y);
  let maxAbs = Math.max(
    Math.abs(Math.min(...xs)),
    Math.abs(Math.max(...xs)),
    Math.abs(Math.min(...ys)),
    Math.abs(Math.max(...ys))
  );
  maxAbs = Math.max(maxAbs, 0.25);
  maxAbs *= 1.15;

  ctx.fillStyle = "rgba(186, 203, 224, 0.75)";
  ctx.font = "11px Segoe UI, sans-serif";
  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;

  const ticks = 5;
  for (let i = 0; i < ticks; i += 1) {
    const ratio = i / (ticks - 1);
    const x = left + ratio * plotWidth;
    const y = top + ratio * plotHeight;

    ctx.beginPath();
    ctx.moveTo(x, top);
    ctx.lineTo(x, top + plotHeight);
    ctx.stroke();

    ctx.beginPath();
    ctx.moveTo(left, y);
    ctx.lineTo(left + plotWidth, y);
    ctx.stroke();
  }

  const x0 = left + ((0 - (-maxAbs)) / (2 * maxAbs)) * plotWidth;
  const y0 = top + (1 - ((0 - (-maxAbs)) / (2 * maxAbs))) * plotHeight;

  ctx.strokeStyle = "rgba(255,255,255,0.4)";
  ctx.lineWidth = 1.25;
  ctx.beginPath();
  ctx.moveTo(x0, top);
  ctx.lineTo(x0, top + plotHeight);
  ctx.stroke();

  ctx.beginPath();
  ctx.moveTo(left, y0);
  ctx.lineTo(left + plotWidth, y0);
  ctx.stroke();

  ctx.fillStyle = "rgba(186, 203, 224, 0.85)";
  ctx.fillText(`-${maxAbs.toFixed(2)} ${unit}`, left, top + plotHeight + 18);
  ctx.fillText(`${maxAbs.toFixed(2)} ${unit}`, left + plotWidth - 48, top + plotHeight + 18);
  ctx.fillText(`Y +${maxAbs.toFixed(2)} ${unit}`, left + 6, top + 12);

  ctx.strokeStyle = "#6dceff";
  ctx.lineWidth = 2;
  ctx.beginPath();
  points.forEach((point, index) => {
    const x = left + ((point.x - (-maxAbs)) / (2 * maxAbs)) * plotWidth;
    const y = top + (1 - (point.y - (-maxAbs)) / (2 * maxAbs)) * plotHeight;
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();

  const latest = points[points.length - 1];
  const latestX = left + ((latest.x - (-maxAbs)) / (2 * maxAbs)) * plotWidth;
  const latestY = top + (1 - (latest.y - (-maxAbs)) / (2 * maxAbs)) * plotHeight;

  ctx.fillStyle = "#ffca66";
  ctx.beginPath();
  ctx.arc(latestX, latestY, 4, 0, Math.PI * 2);
  ctx.fill();
  ctx.fillText(`latest X=${latest.x.toFixed(2)} Y=${latest.y.toFixed(2)} ${unit}`, left + 8, top + 28);
}

function normalizeAngleDeg(angle) {
  let value = angle;
  while (value > 180) {
    value -= 360;
  }
  while (value <= -180) {
    value += 360;
  }
  return value;
}

function gyroMagnitude(sample) {
  if (!sample) {
    return null;
  }
  const gx = Number.isFinite(sample.gyr_x) ? sample.gyr_x : null;
  const gy = Number.isFinite(sample.gyr_y) ? sample.gyr_y : null;
  const gz = Number.isFinite(sample.gyr_z) ? sample.gyr_z : null;
  if (gx === null && gy === null && gz === null) {
    return null;
  }
  return Math.sqrt((gx || 0) ** 2 + (gy || 0) ** 2 + (gz || 0) ** 2);
}

function gyroStabilityLabel(speedDps) {
  if (speedDps === null || speedDps === undefined || !Number.isFinite(speedDps)) {
    return "N/A";
  }
  if (speedDps < 5.0) {
    return "Stable";
  }
  if (speedDps < 25.0) {
    return "Mobile";
  }
  return "Rotation forte";
}

function buildGyroEstimate(samples) {
  const derived = [];
  let rollDeg = 0.0;
  let pitchDeg = 0.0;
  let yawDeg = 0.0;
  let posX = 0.0;
  let posY = 0.0;
  let velX = 0.0;
  let velY = 0.0;
  let lastTs = null;
  let gyroCount = 0;

  for (const sample of samples || []) {
    const gx = Number.isFinite(sample.gyr_x) ? sample.gyr_x : null;
    const gy = Number.isFinite(sample.gyr_y) ? sample.gyr_y : null;
    const gz = Number.isFinite(sample.gyr_z) ? sample.gyr_z : null;
    const hasGyro = gx !== null || gy !== null || gz !== null;

    const currentTs = toTimestampMs(sample);
    let dt = 0.1;
    if (lastTs !== null && currentTs !== null) {
      dt = clamp((currentTs - lastTs) / 1000.0, 0.01, 0.5);
    }

    if (hasGyro) {
      const gxr = gx === null ? 0.0 : gx;
      const gyr = gy === null ? 0.0 : gy;
      const gzr = gz === null ? 0.0 : gz;

      rollDeg += gxr * dt;
      pitchDeg += gyr * dt;
      yawDeg = normalizeAngleDeg(yawDeg + gzr * dt);

      const rollRad = (clamp(rollDeg, -80, 80) * Math.PI) / 180.0;
      const pitchRad = (clamp(pitchDeg, -80, 80) * Math.PI) / 180.0;

      const ax = clamp(9.80665 * Math.tan(pitchRad), -6.0, 6.0);
      const ay = clamp(-9.80665 * Math.tan(rollRad), -6.0, 6.0);

      const damping = Math.exp(-0.45 * dt);
      velX = (velX + ax * dt) * damping;
      velY = (velY + ay * dt) * damping;

      posX += velX * dt;
      posY += velY * dt;
      gyroCount += 1;
    }

    derived.push({
      timestamp: sample.timestamp,
      roll_deg: hasGyro ? rollDeg : null,
      pitch_deg: hasGyro ? pitchDeg : null,
      yaw_deg: hasGyro ? yawDeg : null,
      pos_x_m: hasGyro ? posX : null,
      pos_y_m: hasGyro ? posY : null,
    });

    if (currentTs !== null) {
      lastTs = currentTs;
    }
  }

  return {
    samples: derived,
    hasGyroData: gyroCount > 0,
    latest: derived.length > 0 ? derived[derived.length - 1] : null,
  };
}

function updateView(status, latest, samples) {
  const badge = document.getElementById("link-badge");
  if (replayMode) {
    badge.textContent = "Mode replay";
    badge.className = "badge good";
  } else if (status.link_ok) {
    badge.textContent = "Liaison OK";
    badge.className = "badge good";
  } else {
    badge.textContent = "Liaison perdue";
    badge.className = "badge bad";
  }

  setText("frames-received", `Recues: ${status.frames_received}`);
  setText("frames-rejected", `Rejetees: ${status.frames_rejected}`);
  setText("history-size", `Historique: ${status.history_size}`);
  setText("rx-fps", `Rx: ${fmt(status.rx_fps, 2, " fps")}`);
  setText("jitter", `Jitter: ${fmt(status.jitter_ms, 1, " ms")}`);
  setText("drop-rate", `Perte estimee: ${fmt(status.drop_rate_pct, 2, " %")}`);
  setText("reject-rate", `Rejet: ${fmt(status.reject_rate_pct, 2, " %")}`);
  setText(
    "last-age",
    status.last_frame_age_s === null
      ? "Age derniere trame: N/A"
      : `Age derniere trame: ${status.last_frame_age_s.toFixed(2)} s`
  );

  if (!replayMode) {
    const mode = status.source_mode || "unknown";
    const detail = status.source_detail ? ` (${status.source_detail})` : "";
    setText("mode-label", `Mode: live websocket [${mode}]${detail}`);
  }

  const displaySamples = calibratedSamples(samples || []);
  const displayLatest = calibrateSample(latest);
  const derived = buildGyroEstimate(displaySamples);
  const latestDerived = derived.latest;

  if (displayLatest) {
    const speedDps = gyroMagnitude(displayLatest);
    setText("gyro-x", fmt(displayLatest.gyr_x, 2, " °/s"));
    setText("gyro-y", fmt(displayLatest.gyr_y, 2, " °/s"));
    setText("gyro-z", fmt(displayLatest.gyr_z, 2, " °/s"));
    setText("gyro-speed", fmt(speedDps, 2, " °/s"));
    setText("gyro-stability", gyroStabilityLabel(speedDps));
  }

  if (latestDerived) {
    const px = latestDerived.pos_x_m;
    const py = latestDerived.pos_y_m;
    const dist = Number.isFinite(px) && Number.isFinite(py) ? Math.sqrt(px * px + py * py) : null;
    setText("roll-angle", fmt(latestDerived.roll_deg, 1, " °"));
    setText("pitch-angle", fmt(latestDerived.pitch_deg, 1, " °"));
    setText("yaw-angle", fmt(latestDerived.yaw_deg, 1, " °"));
    setText("pos-x", fmt(px, 2, " m"));
    setText("pos-y", fmt(py, 2, " m"));
    setText("pos-dist", fmt(dist, 2, " m"));
  }

  drawMultiSeries(
    "chart-gyro-rates",
    displaySamples,
    [
      { name: "X", field: "gyr_x", color: "#63b3ff" },
      { name: "Y", field: "gyr_y", color: "#4fe2b5" },
      { name: "Z", field: "gyr_z", color: "#ffca66" },
    ],
    "°/s"
  );

  drawMultiSeries(
    "chart-angles",
    derived.samples,
    [
      { name: "Roll", field: "roll_deg", color: "#6dceff" },
      { name: "Pitch", field: "pitch_deg", color: "#8ef4c2" },
      { name: "Yaw", field: "yaw_deg", color: "#ffd479" },
    ],
    "°"
  );

  drawSeries("chart-yaw", derived.samples, "yaw_deg", "#ffd479", "°");
  drawTrajectory("chart-xy", derived.samples, "pos_x_m", "pos_y_m", "m");

  if (!derived.hasGyroData) {
    setHealth("health-nav", "Navigation gyro", "ABSENTE", "bad");
  } else if ((status.rx_fps || 0) < 6.0) {
    setHealth("health-nav", "Navigation gyro", "INSTABLE", "warn");
  } else {
    setHealth("health-nav", "Navigation gyro", "OK", "good");
  }

  if (!replayMode && !status.link_ok) {
    setHealth("health-link", "Liaison", "PERDUE", "bad");
  } else if (!replayMode && status.rx_fps < 7.0) {
    setHealth("health-link", "Liaison", "INSTABLE", "warn");
  } else {
    setHealth("health-link", "Liaison", replayMode ? "REPLAY" : "OK", "good");
  }

  if (status.reject_rate_pct > 10.0 || status.drop_rate_pct > 10.0) {
    setHealth("health-integrity", "Integrite", "CRITIQUE", "bad");
  } else if (status.reject_rate_pct > 2.0 || status.drop_rate_pct > 2.0) {
    setHealth("health-integrity", "Integrite", "DEGRADEE", "warn");
  } else {
    setHealth("health-integrity", "Integrite", "OK", "good");
  }
}

async function pollOnce() {
  const [statusResp, latestResp, historyResp] = await Promise.all([
    fetch("/api/status"),
    fetch("/api/latest"),
    fetch(`/api/history?points=${MAX_POINTS}`),
  ]);
  const status = await statusResp.json();
  const latestPayload = await latestResp.json();
  const historyPayload = await historyResp.json();
  sampleBuffer = historyPayload.samples || [];
  trimSampleBuffer();
  updateView(status, latestPayload.sample, sampleBuffer);
}

function startPollingFallback() {
  if (pollingTimer !== null) {
    return;
  }
  setText("mode-label", "Mode: fallback HTTP polling");
  const tick = async () => {
    try {
      await pollOnce();
    } catch (err) {
      const badge = document.getElementById("link-badge");
      badge.textContent = "API indisponible";
      badge.className = "badge bad";
    } finally {
      pollingTimer = window.setTimeout(tick, 500);
    }
  };
  tick();
}

function stopPollingFallback() {
  if (pollingTimer !== null) {
    window.clearTimeout(pollingTimer);
    pollingTimer = null;
  }
}

async function switchSource(mode) {
  const response = await fetch("/api/source", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mode }),
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({ detail: "Erreur switch source" }));
    throw new Error(payload.detail || "Erreur switch source");
  }
  replayMode = false;
  sampleBuffer = [];
  lastFrameId = null;
  connectLive();
}

function connectLive() {
  replayMode = false;
  stopPollingFallback();
  setText("mode-label", "Mode: live websocket [connexion...]");

  if (liveSocket) {
    liveSocket.close();
    liveSocket = null;
  }

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const params = new URLSearchParams({
    points: String(MAX_POINTS),
    period_ms: String(WS_PERIOD_MS),
  });
  if (modeOverrideOnce) {
    params.set("mode", modeOverrideOnce);
    modeOverrideOnce = null;
  }
  const url = `${scheme}://${window.location.host}/ws/live?${params.toString()}`;
  const ws = new WebSocket(url);
  liveSocket = ws;

  ws.onmessage = (event) => {
    wsFailures = 0;
    const payload = JSON.parse(event.data);
    if (payload.error) {
      setText("mode-label", `Mode: erreur switch (${payload.error})`);
      return;
    }
    if (Array.isArray(payload.history)) {
      sampleBuffer = payload.history;
      lastFrameId = sampleBuffer.length ? sampleBuffer[sampleBuffer.length - 1].frame_id : null;
    }
    if (Array.isArray(payload.append) && payload.append.length > 0) {
      payload.append.forEach((sample) => {
        if (!sample || sample.frame_id === undefined || sample.frame_id === null) {
          return;
        }
        if (lastFrameId !== null && sample.frame_id === lastFrameId) {
          return;
        }
        sampleBuffer.push(sample);
        lastFrameId = sample.frame_id;
      });
    }
    trimSampleBuffer();
    updateView(payload.status, payload.latest, sampleBuffer);
  };

  ws.onclose = () => {
    if (replayMode) {
      return;
    }
    wsFailures += 1;
    if (wsFailures >= 3) {
      startPollingFallback();
      return;
    }
    const badge = document.getElementById("link-badge");
    badge.textContent = "Reconnexion...";
    badge.className = "badge bad";
    setTimeout(connectLive, 1000);
  };

  ws.onerror = () => {
    ws.close();
  };
}

function parseReplayCsv(text) {
  const lines = text.split(/\r?\n/).filter((line) => line.trim() !== "");
  if (lines.length < 2) {
    return [];
  }
  const headers = lines[0].split(",").map((h) => h.trim());
  const rows = [];
  for (let i = 1; i < lines.length; i += 1) {
    const cols = lines[i].split(",").map((c) => c.trim());
    if (cols.length !== headers.length) {
      continue;
    }
    const row = {};
    for (let j = 0; j < headers.length; j += 1) {
      row[headers[j]] = cols[j];
    }
    rows.push({
      timestamp: row.timestamp,
      frame_id: Number(row.frame_id),
      acc_x: parseNullable(row.acc_x),
      acc_y: parseNullable(row.acc_y),
      acc_z: parseNullable(row.acc_z),
      gyr_x: parseNullable(row.gyr_x),
      gyr_y: parseNullable(row.gyr_y),
      gyr_z: parseNullable(row.gyr_z),
      temp_imu: parseNullable(row.temp_imu),
      pression: parseNullable(row.pression),
      temp_bmp: parseNullable(row.temp_bmp),
      altitude: parseNullable(row.altitude),
      v_bat: parseNullable(row.v_bat),
    });
  }
  return rows;
}

function parseNullable(value) {
  if (value === undefined || value === null || value === "N/A" || value === "") {
    return null;
  }
  return Number(value);
}

function replayStatus(samples) {
  const latest = samples.length > 0 ? samples[samples.length - 1] : null;
  let rxFps = 0.0;
  if (samples.length > 1) {
    const start = Date.parse(samples[0].timestamp);
    const end = Date.parse(samples[samples.length - 1].timestamp);
    if (!Number.isNaN(start) && !Number.isNaN(end) && end > start) {
      rxFps = ((samples.length - 1) * 1000.0) / (end - start);
    }
  }
  return {
    frames_received: samples.length,
    frames_rejected: 0,
    last_frame_age_s: null,
    link_ok: true,
    history_size: samples.length,
    rx_fps: rxFps,
    jitter_ms: 0.0,
    estimated_missing_frames: 0,
    duplicate_frames: 0,
    reject_rate_pct: 0.0,
    drop_rate_pct: 0.0,
    latest,
  };
}

async function loadReplayFile(file) {
  const text = await file.text();
  const samples = parseReplayCsv(text);
  replayMode = true;
  setText("mode-label", `Mode: replay (${samples.length} points)`);
  if (liveSocket) {
    liveSocket.close();
    liveSocket = null;
  }
  stopPollingFallback();
  sampleBuffer = samples.slice(-MAX_POINTS);
  trimSampleBuffer();
  lastFrameId = sampleBuffer.length ? sampleBuffer[sampleBuffer.length - 1].frame_id : null;
  const status = replayStatus(samples);
  updateView(status, status.latest, sampleBuffer);
}

function trimSampleBuffer() {
  if (sampleBuffer.length > MAX_POINTS) {
    sampleBuffer = sampleBuffer.slice(sampleBuffer.length - MAX_POINTS);
  }
}

function initControls() {
  const tareBtn = document.getElementById("tare-gyro-btn");
  if (tareBtn) {
    tareBtn.addEventListener("click", () => {
      const message = tareGyro();
      const latest = sampleBuffer.length ? sampleBuffer[sampleBuffer.length - 1] : null;
      updateView(replayStatus(sampleBuffer), latest, sampleBuffer);
      setText("mode-label", message);
    });
  }

  const simBtn = document.getElementById("mode-sim-btn");
  if (simBtn) {
    simBtn.addEventListener("click", async () => {
      setText("mode-label", "Mode: switch vers simule...");
      try {
        await switchSource("sim");
      } catch (err) {
        modeOverrideOnce = "sim";
        connectLive();
      }
    });
  }

  const realBtn = document.getElementById("mode-real-btn");
  if (realBtn) {
    realBtn.addEventListener("click", async () => {
      setText("mode-label", "Mode: switch vers reel...");
      try {
        await switchSource("serial");
      } catch (err) {
        modeOverrideOnce = "serial";
        connectLive();
      }
    });
  }

  const liveBtn = document.getElementById("live-btn");
  if (liveBtn) {
    liveBtn.addEventListener("click", () => {
      connectLive();
    });
  }

  const replayInput = document.getElementById("replay-file");
  if (replayInput) {
    replayInput.addEventListener("change", async (event) => {
      const file = event.target.files && event.target.files[0];
      if (!file) {
        return;
      }
      try {
        await loadReplayFile(file);
      } catch (err) {
        setText("mode-label", "Mode: replay invalide");
      }
    });
  }
}

initControls();
connectLive();
