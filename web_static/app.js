const MAX_POINTS = 120;
const WS_PERIOD_MS = 250;

let liveSocket = null;
let replayMode = false;

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

function drawSeries(canvasId, values, color) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) {
    return;
  }
  const ctx = canvas.getContext("2d");
  const width = canvas.width;
  const height = canvas.height;
  ctx.clearRect(0, 0, width, height);

  const filtered = values.filter((v) => v !== null && v !== undefined);
  if (filtered.length === 0) {
    return;
  }

  let min = Math.min(...filtered);
  let max = Math.max(...filtered);
  if (min === max) {
    min -= 1;
    max += 1;
  }
  const pad = (max - min) * 0.15;
  min -= pad;
  max += pad;

  ctx.strokeStyle = "rgba(255,255,255,0.18)";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(0, height - 1);
  ctx.lineTo(width, height - 1);
  ctx.stroke();

  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();

  values.forEach((value, idx) => {
    if (value === null || value === undefined) {
      return;
    }
    const x = (idx / Math.max(values.length - 1, 1)) * width;
    const y = height - ((value - min) / (max - min)) * height;
    if (idx === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.stroke();
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

  if (latest) {
    setText("frame-id", String(latest.frame_id));
    setText("altitude", fmt(latest.altitude, 2, " m"));
    setText("pression", fmt(latest.pression, 2, " hPa"));
    setText("vbat", fmt(latest.v_bat, 3, " V"));
    setText("temp-imu", fmt(latest.temp_imu, 2, " °C"));
    setText("temp-bmp", fmt(latest.temp_bmp, 2, " °C"));
  }

  const altitude = (samples || []).map((s) => s.altitude);
  const pression = (samples || []).map((s) => s.pression);
  const vbat = (samples || []).map((s) => s.v_bat);

  drawSeries("chart-altitude", altitude, "#63b3ff");
  drawSeries("chart-pression", pression, "#4fe2b5");
  drawSeries("chart-vbat", vbat, "#ffca66");

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

function connectLive() {
  replayMode = false;
  setText("mode-label", "Mode: live websocket");

  if (liveSocket) {
    liveSocket.close();
    liveSocket = null;
  }

  const scheme = window.location.protocol === "https:" ? "wss" : "ws";
  const url = `${scheme}://${window.location.host}/ws/live?points=${MAX_POINTS}&period_ms=${WS_PERIOD_MS}`;
  const ws = new WebSocket(url);
  liveSocket = ws;

  ws.onmessage = (event) => {
    const payload = JSON.parse(event.data);
    updateView(payload.status, payload.latest, payload.history);
  };

  ws.onclose = () => {
    if (replayMode) {
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
  const status = replayStatus(samples);
  updateView(status, status.latest, samples.slice(-MAX_POINTS));
}

function initControls() {
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
