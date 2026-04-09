const MAX_POINTS = 20000;
const WS_PERIOD_MS = 250;

let liveSocket = null;
let replayMode = false;
let wsFailures = 0;
let pollingTimer = null;
let modeOverrideOnce = null;
let sampleBuffer = [];
let lastFrameId = null;

function fmt(value, decimals = 3, unit = "") {
  if (value === null || value === undefined) {
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
    return 0.02;
  }
  if (unit === "hPa") {
    return 0.02;
  }
  return 0.1;
}

function drawSeries(canvasId, samples, field, color, unit) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const values = (samples || []).map((s) => s[field]);
  const filtered = values.filter((v) => v !== null && v !== undefined && Number.isFinite(v));

  const left = 54;
  const right = 8;
  const top = 8;
  const bottom = 22;
  const plotWidth = width - left - right;
  const plotHeight = height - top - bottom;

  ctx.fillStyle = "rgba(186, 203, 224, 0.75)";
  ctx.font = "11px Segoe UI, sans-serif";

  if (filtered.length === 0 || values.length < 2) {
    ctx.fillText("No data", left + 8, top + 14);
    return;
  }

  let min = Math.min(...filtered);
  let max = Math.max(...filtered);
  const rawMin = min;
  const rawMax = max;
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
  const span = max - min;
  const pad = span * 0.12;
  min -= pad;
  max += pad;
  const range = max - min;
  const decimals = decimalsForSpan(range);

  const yTicks = 5;
  ctx.strokeStyle = "rgba(255,255,255,0.12)";
  ctx.lineWidth = 1;
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
  const timestamps = (samples || []).map((s) => Date.parse(s.timestamp || ""));
  const validTs = timestamps.filter((t) => Number.isFinite(t));
  const tMin = validTs.length ? Math.min(...validTs) : 0;
  const tMax = validTs.length ? Math.max(...validTs) : 1;
  const fallbackDurationMs = Math.max((values.length - 1) * WS_PERIOD_MS, 1);
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

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  let penDown = false;
  values.forEach((value, idx) => {
    if (value === null || value === undefined || !Number.isFinite(value)) {
      penDown = false;
      return;
    }
    const x = left + (idx / Math.max(values.length - 1, 1)) * plotWidth;
    const y = top + (1 - (value - min) / (max - min)) * plotHeight;
    if (!penDown) {
      ctx.moveTo(x, y);
      penDown = true;
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();

  const latest = filtered[filtered.length - 1];
  ctx.fillStyle = color;
  ctx.fillText(`latest ${latest.toFixed(Math.max(3, decimals))} ${unit}`, left + 6, top + 12);
  ctx.fillText(
    `range ${rawMin.toFixed(Math.max(3, decimals))} .. ${rawMax.toFixed(Math.max(3, decimals))} ${unit}`,
    left + 6,
    top + 24
  );
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

  if (latest) {
    setText("frame-id", String(latest.frame_id));
    setText("altitude", fmt(latest.altitude, 2, " m"));
    setText("pression", fmt(latest.pression, 2, " hPa"));
    setText("vbat", fmt(latest.v_bat, 3, " V"));
    setText("temp-imu", fmt(latest.temp_imu, 2, " °C"));
    setText("temp-bmp", fmt(latest.temp_bmp, 2, " °C"));
  }

  drawSeries("chart-altitude", samples || [], "altitude", "#63b3ff", "m");
  drawSeries("chart-pression", samples || [], "pression", "#4fe2b5", "hPa");
  drawSeries("chart-vbat", samples || [], "v_bat", "#ffca66", "V");

  if (latest) {
    const battery = latest.v_bat;
    const tempImu = latest.temp_imu;
    const tempBmp = latest.temp_bmp;

    if (battery === null || battery === undefined) {
      setHealth("health-battery", "Batterie", "N/A", "bad");
    } else if (battery < 3.4) {
      setHealth("health-battery", "Batterie", `${battery.toFixed(2)} V`, "bad");
    } else if (battery < 3.6) {
      setHealth("health-battery", "Batterie", `${battery.toFixed(2)} V`, "warn");
    } else {
      setHealth("health-battery", "Batterie", `${battery.toFixed(2)} V`, "good");
    }

    const maxTemp = Math.max(
      tempImu === null ? -1000 : tempImu,
      tempBmp === null ? -1000 : tempBmp
    );
    if (maxTemp > 70) {
      setHealth("health-temp", "Temperature", `${maxTemp.toFixed(1)} °C`, "bad");
    } else if (maxTemp > 55) {
      setHealth("health-temp", "Temperature", `${maxTemp.toFixed(1)} °C`, "warn");
    } else {
      setHealth("health-temp", "Temperature", `${maxTemp.toFixed(1)} °C`, "good");
    }
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
  const simBtn = document.getElementById("mode-sim-btn");
  if (simBtn) {
    simBtn.addEventListener("click", async () => {
      setText("mode-label", "Mode: switch vers simulé...");
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
      setText("mode-label", "Mode: switch vers réel...");
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
