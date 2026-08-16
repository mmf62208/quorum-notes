const $ = (id) => document.getElementById(id);

let currentId = null;
let recCtx = null;
let recProc = null;
let recStream = null;
let recChunks = [];

function lines(text) {
  return String(text || "")
    .split(/\r?\n/)
    .map((s) => s.trim())
    .filter(Boolean);
}

function parseReports(text) {
  return lines(text).map((row) => {
    const [title = "", presenter = "", ...rest] = row.split("|").map((s) => s.trim());
    return { title, presenter, body: rest.join(" | ") };
  });
}

function parseMotions(text) {
  return lines(text).map((row) => {
    const [body = "", mover = "", seconder = "", yeas = "0", nays = "0", result = "pending"] = row
      .split("|")
      .map((s) => s.trim());
    return {
      text: body,
      mover,
      seconder,
      yeas: Number(yeas) || 0,
      nays: Number(nays) || 0,
      abstain: 0,
      result: result || "pending",
    };
  });
}

function formPayload() {
  return {
    organization: $("organization").value.trim(),
    title: $("title").value.trim() || "Regular Meeting",
    date: $("date").value,
    location: $("location").value.trim(),
    called_to_order_by: $("called_to_order_by").value.trim(),
    submitted_by: $("submitted_by").value.trim(),
    submitted_office: $("submitted_office").value.trim() || "Adjutant",
    roster: lines($("roster").value),
    present: lines($("present").value),
    quorum_rule: $("quorum_rule").value,
    quorum_fixed: Number($("quorum_fixed").value) || 0,
    opening: lines($("opening").value),
    previous_minutes: $("previous_minutes").value,
    previous_minutes_note: $("previous_minutes_note").value.trim(),
    reports: parseReports($("reports").value),
    old_business: lines($("old_business").value),
    new_business: parseMotions($("new_business").value),
    announcements: lines($("announcements").value),
    adjournment: $("adjournment").value.trim(),
    notes: $("notes").value,
  };
}

function fillForm(m) {
  $("organization").value = m.organization || "";
  $("title").value = m.title || "";
  $("date").value = m.date || "";
  $("location").value = m.location || "";
  $("called_to_order_by").value = m.called_to_order_by || "";
  $("submitted_by").value = m.submitted_by || "";
  $("submitted_office").value = m.submitted_office || "Adjutant";
  $("roster").value = (m.roster || []).join("\n");
  $("present").value = (m.present || []).join("\n");
  $("quorum_rule").value = m.quorum_rule || "majority";
  $("quorum_fixed").value = m.quorum_fixed || 0;
  $("opening").value = (m.opening || []).join("\n");
  $("previous_minutes").value = m.previous_minutes || "pending";
  $("previous_minutes_note").value = m.previous_minutes_note || "";
  $("reports").value = (m.reports || [])
    .map((r) => [r.title, r.presenter, r.body].filter(Boolean).join(" | "))
    .join("\n");
  $("old_business").value = (m.old_business || []).join("\n");
  $("new_business").value = (m.new_business || [])
    .map((x) => [x.text, x.mover, x.seconder, x.yeas, x.nays, x.result].join(" | "))
    .join("\n");
  $("announcements").value = (m.announcements || []).join("\n");
  $("adjournment").value = m.adjournment || "";
  $("notes").value = m.notes || "";
  updateQuorum();
}

function updateQuorum() {
  const roster = lines($("roster").value);
  const present = lines($("present").value);
  const rule = $("quorum_rule").value;
  const required = rule === "fixed" ? Number($("quorum_fixed").value) || 0 : roster.length ? Math.floor(roster.length / 2) + 1 : 0;
  const ok = required === 0 ? present.length > 0 : present.length >= required;
  const el = $("quorum-out");
  el.textContent = ok
    ? `Quorum present · ${present.length} of ${required} required`
    : `No quorum · ${present.length} of ${required} required`;
  el.className = "quorum-out " + (ok ? "yes" : "no");
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

async function refreshList() {
  const { meetings } = await api("/api/meetings");
  const ul = $("meeting-list");
  ul.innerHTML = "";
  meetings.forEach((m) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = m.id === currentId ? "active" : "";
    b.textContent = `${m.date || "undated"} — ${m.organization || m.title || m.id}`;
    b.onclick = () => openMeeting(m.id);
    li.appendChild(b);
    ul.appendChild(li);
  });
}

async function openMeeting(id) {
  const data = await api(`/api/meetings/${id}`);
  currentId = id;
  $("editor").hidden = false;
  fillForm(data.meeting);
  $("minutes").textContent = data.markdown;
  const player = $("player");
  if (data.meeting.has_audio) {
    player.hidden = false;
    player.src = `/api/meetings/${id}/audio?t=${Date.now()}`;
    $("rec-status").textContent = "WAV in vault";
  } else {
    player.hidden = true;
    player.removeAttribute("src");
    $("rec-status").textContent = "No recording";
  }
  await refreshList();
}

async function saveMeeting() {
  if (!currentId) return;
  const data = await api(`/api/meetings/${currentId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(formPayload()),
  });
  $("minutes").textContent = data.markdown;
  $("save-status").textContent = `Saved ${new Date().toLocaleTimeString()}`;
  await refreshList();
}

function encodeWav(floatChunks, sampleRate) {
  let length = 0;
  floatChunks.forEach((c) => {
    length += c.length;
  });
  const pcm = new Int16Array(length);
  let offset = 0;
  floatChunks.forEach((c) => {
    for (let i = 0; i < c.length; i += 1) {
      const s = Math.max(-1, Math.min(1, c[i]));
      pcm[offset + i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    offset += c.length;
  });
  const bytes = pcm.byteLength;
  const buffer = new ArrayBuffer(44 + bytes);
  const view = new DataView(buffer);
  const writeStr = (o, s) => {
    for (let i = 0; i < s.length; i += 1) view.setUint8(o + i, s.charCodeAt(i));
  };
  writeStr(0, "RIFF");
  view.setUint32(4, 36 + bytes, true);
  writeStr(8, "WAVE");
  writeStr(12, "fmt ");
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  writeStr(36, "data");
  view.setUint32(40, bytes, true);
  new Uint8Array(buffer, 44).set(new Uint8Array(pcm.buffer));
  return new Blob([buffer], { type: "audio/wav" });
}

async function startRec() {
  recStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recCtx = new AudioContext();
  const src = recCtx.createMediaStreamSource(recStream);
  recProc = recCtx.createScriptProcessor(4096, 1, 1);
  recChunks = [];
  recProc.onaudioprocess = (ev) => {
    recChunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
  };
  src.connect(recProc);
  recProc.connect(recCtx.destination);
  $("btn-rec").disabled = true;
  $("btn-stop").disabled = false;
  $("rec-status").textContent = "Recording…";
  $("rec-status").className = "live";
}

async function stopRec() {
  if (recProc) recProc.disconnect();
  if (recStream) recStream.getTracks().forEach((t) => t.stop());
  const rate = recCtx ? recCtx.sampleRate : 44100;
  if (recCtx) await recCtx.close();
  recProc = null;
  recCtx = null;
  recStream = null;
  $("btn-rec").disabled = false;
  $("btn-stop").disabled = true;
  $("rec-status").className = "";
  const blob = encodeWav(recChunks, rate);
  recChunks = [];
  if (!currentId) return;
  await fetch(`/api/meetings/${currentId}/audio`, { method: "POST", body: blob });
  $("player").hidden = false;
  $("player").src = `/api/meetings/${currentId}/audio?t=${Date.now()}`;
  $("rec-status").textContent = `Saved WAV (${Math.round(blob.size / 1024)} KB)`;
}

function salTemplate() {
  $("organization").value = "SAL Post 484 Squadron";
  $("title").value = "Regular Meeting";
  $("location").value = "Post home";
  $("called_to_order_by").value = "Commander Jeff Shumaker";
  $("submitted_by").value = "Mike Featherstone";
  $("submitted_office").value = "Adjutant, SAL Post 484";
  $("roster").value = [
    "Jeff Shumaker",
    "Herm Clear",
    "Gene Newell",
    "Mike Featherstone",
    "Ted Ruser",
    "Kirk Dewey",
    "Paul Nichols",
    "William Wood",
    "Mike Gerlofs",
    "Randy Robbins",
    "William Fayling",
  ].join("\n");
  $("opening").value = [
    "Chaplain Herm Clear offered the opening prayer.",
    "Commander Jeff Shumaker led the Pledge of Allegiance.",
    "A moment of silence was observed in honor of POW/MIA.",
  ].join("\n");
  $("previous_minutes").value = "approved";
  updateQuorum();
}

async function boot() {
  const status = await api("/api/status");
  $("vault-path").textContent = status.vault;
  const badge = $("ai-badge");
  if (status.ai.enabled) {
    badge.textContent = `SpaceXAI ready · ${status.ai.model}`;
    badge.classList.add("on");
  }
  await refreshList();
}

$("roster").addEventListener("input", updateQuorum);
$("present").addEventListener("input", updateQuorum);
$("quorum_rule").addEventListener("change", updateQuorum);
$("quorum_fixed").addEventListener("input", updateQuorum);
$("btn-new").onclick = async () => {
  const today = new Date().toISOString().slice(0, 10);
  const data = await api("/api/meetings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ date: today, title: "Regular Meeting" }),
  });
  await openMeeting(data.meeting.id);
};
$("btn-save").onclick = () => saveMeeting().catch((e) => { $("save-status").textContent = e.message; });
$("btn-sal").onclick = salTemplate;
$("btn-backup").onclick = async () => {
  const data = await api("/api/backup", { method: "POST" });
  $("save-status").textContent = `Backup ${data.name}`;
};
$("btn-delete").onclick = async () => {
  if (!currentId || !confirm("Delete this meeting from the local vault?")) return;
  await api(`/api/meetings/${currentId}`, { method: "DELETE" });
  currentId = null;
  $("editor").hidden = true;
  await refreshList();
};
$("btn-rec").onclick = () => startRec().catch((e) => { $("rec-status").textContent = e.message; });
$("btn-stop").onclick = () => stopRec().catch((e) => { $("rec-status").textContent = e.message; });
$("btn-transcribe").onclick = async () => {
  if (!currentId) return;
  $("save-status").textContent = "Sending WAV to SpaceXAI STT (opt-in)…";
  try {
    const data = await api(`/api/meetings/${currentId}/transcribe`, { method: "POST" });
    $("notes").value = [$("notes").value, data.transcript].filter(Boolean).join("\n\n");
    $("save-status").textContent = "Transcript saved locally.";
  } catch (e) {
    $("save-status").textContent = e.message;
  }
};
$("btn-draft").onclick = async () => {
  if (!currentId) return;
  await saveMeeting();
  $("save-status").textContent = "Requesting SpaceXAI draft (opt-in)…";
  try {
    const data = await api(`/api/meetings/${currentId}/draft`, { method: "POST" });
    $("minutes").textContent = data.markdown;
    $("save-status").textContent = "Draft returned. Review before treating it as official minutes.";
  } catch (e) {
    $("save-status").textContent = e.message;
  }
};

boot().catch((e) => {
  $("vault-path").textContent = e.message;
});
