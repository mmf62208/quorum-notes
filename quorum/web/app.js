const $ = (id) => document.getElementById(id);

let settings = {};
let current = null;
let rec = { ctx: null, proc: null, stream: null, chunks: [], started: 0, analyser: null, raf: 0 };
let pendingRole = null;
let playbackRate = 1;

function lines(text) {
  return String(text || "").split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || res.statusText);
  return data;
}

function emptyMeeting(partial = {}) {
  return {
    id: "",
    title: "Regular Meeting",
    organization: settings.organization || "",
    date: new Date().toISOString().slice(0, 10),
    location: settings.default_location || "Post home",
    called_to_order_by: settings.called_to_order_by || "",
    submitted_by: settings.submitted_by || "",
    submitted_office: settings.submitted_office || "",
    roster: [...(settings.roster || [])],
    present: [],
    late: [],
    guests: [],
    opening: [],
    reports: [],
    old_business: [],
    new_business: [],
    announcements: [],
    takeaways: [],
    speaker_marks: [],
    photos: [],
    notes: "",
    adjournment: "",
    roberts: settings.roberts !== false,
    minutes_approved: false,
    has_audio: false,
    ...partial,
  };
}

function fillHeader() {
  $("organization").value = current.organization || "";
  $("title").value = current.title || "Regular Meeting";
  $("date").value = current.date || "";
  $("location").value = current.location || "";
  $("called_to_order_by").value = current.called_to_order_by || "";
  $("submitted_by").value = current.submitted_by || "";
  $("submitted_office").value = current.submitted_office || "";
  $("notes").value = current.notes || "";
  $("adjournment").value = current.adjournment || "";
  $("previous_minutes_note").value = current.previous_minutes_note || "";
  $("opening-text").textContent = (current.opening || []).join(" ");
  $("rr-block").hidden = current.roberts === false;
  renderLists();
  showStep(current.agenda_index || 0);
}

function readHeader() {
  current.organization = $("organization").value.trim();
  current.title = $("title").value.trim() || "Regular Meeting";
  current.date = $("date").value;
  current.location = $("location").value.trim();
  current.called_to_order_by = $("called_to_order_by").value.trim();
  current.submitted_by = $("submitted_by").value.trim();
  current.submitted_office = $("submitted_office").value.trim();
  current.notes = $("notes").value;
  current.adjournment = $("adjournment").value.trim();
  current.previous_minutes_note = $("previous_minutes_note").value.trim();
}

const STEP_IDS = [
  "opening",
  "roll_call",
  "previous_minutes",
  "reports",
  "old_business",
  "new_business",
  "announcements",
  "adjournment",
];

function showStep(index) {
  if (!current) return;
  current.agenda_index = Math.max(0, Math.min(STEP_IDS.length - 1, Number(index) || 0));
  STEP_IDS.forEach((id, i) => {
    const panel = $(`step-${id}`);
    if (panel) panel.hidden = i !== current.agenda_index;
  });
  const nav = $("agenda");
  nav.innerHTML = "";
  STEP_IDS.forEach((id, i) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = id.replaceAll("_", " ");
    if (i === current.agenda_index) b.classList.add("talking");
    b.onclick = () => {
      showStep(i);
      saveMeeting().catch(() => {});
    };
    nav.appendChild(b);
  });
  $("step-label").textContent = STEP_IDS[current.agenda_index].replaceAll("_", " ");
}

function renderLists() {
  $("report-list").innerHTML = (current.reports || [])
    .map((r) => `<li><strong>${r.title}</strong> ${r.presenter || ""} — ${r.body || ""}</li>`)
    .join("");
  $("old-list").innerHTML = (current.old_business || []).map((t) => `<li>${t}</li>`).join("");
  $("announce-list").innerHTML = (current.announcements || []).map((t) => `<li>${t}</li>`).join("");
}

function renderPeople() {
  const box = $("people");
  box.innerHTML = "";
  const names = [...new Set([...(current.roster || []), ...(current.present || []), ...(current.guests || [])])];
  names.forEach((name) => {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = name;
    if ((current.present || []).includes(name)) b.classList.add("present");
    if ((current.late || []).includes(name)) b.classList.add("late");
    const last = (current.speaker_marks || []).at(-1);
    if (last && last.name === name && rec.started) b.classList.add("talking");
    b.onclick = () => onPerson(name);
    box.appendChild(b);
  });
  renderMarks();
}

function renderMarks() {
  const box = $("marks");
  if (!box) return;
  box.innerHTML = "";
  (current.speaker_marks || []).forEach((mark) => {
    const b = document.createElement("button");
    const mins = Math.floor(mark.seconds / 60);
    const secs = String(Math.floor(mark.seconds % 60)).padStart(2, "0");
    b.type = "button";
    b.textContent = `${mins}:${secs} ${mark.name}`;
    b.onclick = () => {
      const player = $("player");
      player.currentTime = mark.seconds;
      player.play().catch(() => {});
    };
    box.appendChild(b);
  });
}

function onPerson(name) {
  if (rec.started) {
    const seconds = (Date.now() - rec.started) / 1000;
    current.speaker_marks = current.speaker_marks || [];
    current.speaker_marks.push({ seconds, name });
    if (!(current.present || []).includes(name)) current.present.push(name);
    $("save-status").textContent = `${name} marked speaking`;
    renderPeople();
    return;
  }
  if (pendingRole === "1st" || pendingRole === "2nd") {
    applyMotionPerson(name);
    return;
  }
  if (pendingRole === "late") {
    current.late = current.late || [];
    if (!current.late.includes(name)) current.late.push(name);
    if (!(current.present || []).includes(name)) current.present.push(name);
    pendingRole = null;
    $("save-status").textContent = `${name} arrived late`;
    renderPeople();
    updateQuorum();
    return;
  }
  const present = new Set(current.present || []);
  if (present.has(name)) present.delete(name);
  else present.add(name);
  current.present = [...present];
  renderPeople();
  updateQuorum();
}

function updateQuorum() {
  const roster = current.roster || [];
  const present = current.present || [];
  const required = roster.length ? Math.floor(roster.length / 2) + 1 : 0;
  const ok = required === 0 ? present.length > 0 : present.length >= required;
  const el = $("quorum-out");
  el.textContent = ok
    ? `Quorum yes · ${present.length} present · ${required} required`
    : `No quorum · ${present.length} present · ${required} required`;
  el.className = "quorum-out " + (ok ? "yes" : "no");
}

function renderMotions() {
  const ul = $("motion-list");
  ul.innerHTML = "";
  (current.new_business || []).forEach((m, i) => {
    const li = document.createElement("li");
    li.textContent = `${m.text} — 1st ${m.mover || "?"} · 2nd ${m.seconder || "none"} · ${m.result} (Y${m.yeas || 0}/N${m.nays || 0})`;
    li.onclick = () => {
      current.new_business.splice(i, 1);
      renderMotions();
    };
    ul.appendChild(li);
  });
}

function draftMotion() {
  return {
    text: $("motion-text").value.trim(),
    mover: "",
    seconder: "",
    yeas: 0,
    nays: 0,
    abstain: 0,
    result: "pending",
  };
}

function currentMotion() {
  current.new_business = current.new_business || [];
  if (!current.new_business.length || current.new_business.at(-1).result !== "pending") {
    const m = draftMotion();
    if (!m.text) return null;
    current.new_business.push(m);
  }
  return current.new_business.at(-1);
}

function applyMotionPerson(name) {
  const m = currentMotion();
  if (!m) {
    $("motion-status").textContent = "Type the motion first.";
    pendingRole = null;
    return;
  }
  if (pendingRole === "1st") m.mover = name;
  if (pendingRole === "2nd") m.seconder = name;
  pendingRole = null;
  $("motion-status").textContent = `1st ${m.mover || "?"} · 2nd ${m.seconder || "needed"}`;
  renderMotions();
}

function renderTakeaways() {
  $("takeaway-list").innerHTML = (current.takeaways || [])
    .map((t) => `<li>${t.text}${t.owner ? " — " + t.owner : ""}</li>`)
    .join("");
}

function renderPhotos() {
  const box = $("photos");
  box.innerHTML = "";
  (current.photos || []).forEach((p) => {
    const img = document.createElement("img");
    img.src = p.data_url;
    img.alt = p.name;
    box.appendChild(img);
  });
}

async function refreshList() {
  const { meetings } = await api("/api/meetings");
  const ul = $("meeting-list");
  ul.innerHTML = "";
  meetings.forEach((m) => {
    const li = document.createElement("li");
    const b = document.createElement("button");
    b.type = "button";
    b.className = current && m.id === current.id ? "active" : "";
    b.textContent = `${m.date || ""} ${m.title || m.file_stem || m.id}`;
    b.onclick = () => openMeeting(m.id);
    li.appendChild(b);
    ul.appendChild(li);
  });
}

async function openMeeting(id) {
  const data = await api(`/api/meetings/${id}`);
  current = data.meeting;
  $("console").hidden = false;
  fillHeader();
  renderPeople();
  renderMotions();
  renderTakeaways();
  renderPhotos();
  updateQuorum();
  $("minutes").textContent = data.markdown;
  $("player").src = current.has_audio ? `/api/meetings/${id}/audio?t=${Date.now()}` : "";
  $("btn-download").href = `/api/meetings/${id}/minutes.md`;
  $("btn-download").setAttribute("download", `${current.file_stem || id}-minutes.md`);
  $("btn-print").href = `/api/meetings/${id}/print.html`;
  await refreshList();
  armMic().catch(() => {});
}

async function saveMeeting() {
  if (!current || !current.id) return;
  readHeader();
  const data = await api(`/api/meetings/${current.id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(current),
  });
  current = data.meeting;
  $("minutes").textContent = data.markdown;
  renderLists();
  showStep(current.agenda_index || 0);
  $("save-status").textContent = `Saved ${new Date().toLocaleTimeString()}`;
  await refreshList();
}

function setMeter(level) {
  const fill = $("meter-fill");
  const wrap = fill.parentElement;
  const pct = Math.min(100, Math.round(level * 140));
  fill.style.width = `${pct}%`;
  wrap.className = "meter";
  if (level < 0.04) wrap.classList.add("quiet");
  else if (level > 0.55) wrap.classList.add("hot");
  $("meter-label").textContent =
    level < 0.04 ? "Too quiet — move closer or pick another mic" : level > 0.55 ? "Hot / loud" : "Hearing the room";
}

function tickMeter() {
  if (!rec.analyser) return;
  const buf = new Uint8Array(rec.analyser.fftSize);
  rec.analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i += 1) {
    const v = (buf[i] - 128) / 128;
    sum += v * v;
  }
  setMeter(Math.sqrt(sum / buf.length));
  if (rec.started) {
    const s = Math.floor((Date.now() - rec.started) / 1000);
    $("clock").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  }
  rec.raf = requestAnimationFrame(tickMeter);
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

function selectedMicId() {
  return $("mic-device") ? $("mic-device").value : "";
}

async function fillMics() {
  const sel = $("mic-device");
  if (!sel || !navigator.mediaDevices?.enumerateDevices) return;
  const devices = await navigator.mediaDevices.enumerateDevices();
  const inputs = devices.filter((d) => d.kind === "audioinput");
  const prev = sel.value;
  sel.innerHTML = "";
  if (!inputs.length) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "Default microphone";
    sel.appendChild(opt);
    return;
  }
  inputs.forEach((d, i) => {
    const opt = document.createElement("option");
    opt.value = d.deviceId;
    opt.textContent = d.label || `Microphone ${i + 1}`;
    sel.appendChild(opt);
  });
  if (prev && [...sel.options].some((o) => o.value === prev)) sel.value = prev;
}

async function openMic(recordChunks) {
  if (rec.stream) rec.stream.getTracks().forEach((t) => t.stop());
  if (rec.ctx) await rec.ctx.close().catch(() => {});
  cancelAnimationFrame(rec.raf);
  const constraint = selectedMicId()
    ? { audio: { deviceId: { exact: selectedMicId() } } }
    : { audio: true };
  rec.stream = await navigator.mediaDevices.getUserMedia(constraint);
  rec.ctx = new AudioContext();
  const src = rec.ctx.createMediaStreamSource(rec.stream);
  rec.analyser = rec.ctx.createAnalyser();
  rec.analyser.fftSize = 2048;
  src.connect(rec.analyser);
  rec.proc = null;
  rec.chunks = [];
  if (recordChunks) {
    rec.proc = rec.ctx.createScriptProcessor(4096, 1, 1);
    rec.proc.onaudioprocess = (ev) => {
      rec.chunks.push(new Float32Array(ev.inputBuffer.getChannelData(0)));
    };
    src.connect(rec.proc);
    rec.proc.connect(rec.ctx.destination);
  }
  await fillMics();
  tickMeter();
}

async function armMic() {
  await openMic(false);
  $("meter-label").textContent = "Listening — confirm the meter moves before Record";
}

async function startRec() {
  await openMic(true);
  rec.started = Date.now();
  $("btn-rec").disabled = true;
  $("btn-rec").classList.add("hot");
  $("btn-stop").disabled = false;
  $("rec-banner").hidden = false;
}

async function stopRec() {
  if (rec.proc) rec.proc.disconnect();
  const chunks = rec.chunks;
  const rate = rec.ctx ? rec.ctx.sampleRate : 44100;
  if (rec.stream) rec.stream.getTracks().forEach((t) => t.stop());
  cancelAnimationFrame(rec.raf);
  if (rec.ctx) await rec.ctx.close();
  rec = { ctx: null, proc: null, stream: null, chunks: [], started: 0, analyser: null, raf: 0 };
  $("btn-rec").disabled = false;
  $("btn-rec").classList.remove("hot");
  $("btn-stop").disabled = true;
  $("rec-banner").hidden = true;
  $("meter-label").textContent = "Saved recording";
  if (!current?.id) return;
  const blob = encodeWav(chunks, rate);
  await fetch(`/api/meetings/${current.id}/audio`, { method: "POST", body: blob });
  $("player").src = `/api/meetings/${current.id}/audio?t=${Date.now()}`;
  current.has_audio = true;
  await saveMeeting();
  armMic().catch(() => {});
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

async function addPhoto(file, kind) {
  if (!file || !current) return;
  const data_url = await fileToDataUrl(file);
  current.photos = current.photos || [];
  current.photos.push({ name: file.name || kind, kind, data_url });
  renderPhotos();
  await saveMeeting();
}

function mailto(subject, body) {
  const url = `mailto:?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
  window.location.href = url;
}

function showWizard(force = false) {
  if (settings.setup_complete && !force) {
    $("wizard").hidden = true;
    return;
  }
  $("wiz-org").value = settings.organization || "";
  $("wiz-name").value = settings.submitted_by || "";
  $("wiz-office").value = settings.submitted_office || "";
  $("wiz-template").value = settings.template || "sal";
  $("wiz-retention").value = settings.retention || "until_approved";
  $("wiz-roberts").checked = settings.roberts !== false;
  $("wiz-roster").value = (settings.roster || []).join("\n");
  $("wizard").hidden = false;
}

async function boot() {
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  const status = await api("/api/status");
  settings = status.settings || {};
  const urls = (status.lan_urls || []).join(" · ");
  $("vault-path").textContent = `${status.vault} · retention: ${settings.retention || "until_approved"}${urls ? " · phones: " + urls : ""}`;
  showWizard();
  await refreshList();
}

$("btn-wiz-save").onclick = async () => {
  settings = await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      setup_complete: true,
      organization: $("wiz-org").value.trim(),
      submitted_by: $("wiz-name").value.trim(),
      submitted_office: $("wiz-office").value.trim(),
      template: $("wiz-template").value,
      retention: $("wiz-retention").value,
      roberts: $("wiz-roberts").checked,
      roster: lines($("wiz-roster").value),
    }),
  }).then((d) => d.settings);
  $("wizard").hidden = true;
};

$("btn-setup").onclick = () => showWizard(true);
$("btn-demo").onclick = async () => {
  const data = await api("/api/demo", { method: "POST" });
  await openMeeting(data.meeting.id);
};
$("btn-new").onclick = async () => {
  const data = await api("/api/meetings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Regular Meeting" }),
  });
  await openMeeting(data.meeting.id);
};
$("btn-save").onclick = () => saveMeeting().catch((e) => { $("save-status").textContent = e.message; });
$("btn-rec").onclick = () => startRec().catch((e) => { $("meter-label").textContent = e.message; });
$("btn-stop").onclick = () => stopRec().catch((e) => { $("meter-label").textContent = e.message; });
$("btn-arm-mic").onclick = () => armMic().catch((e) => { $("meter-label").textContent = e.message; });
$("mic-device").onchange = () => armMic().catch((e) => { $("meter-label").textContent = e.message; });
$("btn-back15").onclick = () => {
  const p = $("player");
  p.currentTime = Math.max(0, (p.currentTime || 0) - 15);
};
$("btn-fwd15").onclick = () => {
  const p = $("player");
  p.currentTime = (p.currentTime || 0) + 15;
};
$("btn-speed").onclick = () => {
  playbackRate = playbackRate === 1 ? 1.5 : playbackRate === 1.5 ? 2 : 1;
  $("player").playbackRate = playbackRate;
  $("btn-speed").textContent = `${playbackRate}×`;
};
$("btn-late").onclick = () => {
  pendingRole = "late";
  $("save-status").textContent = "Tap who arrived late.";
};
$("btn-prev-step").onclick = () => {
  showStep((current.agenda_index || 0) - 1);
  saveMeeting().catch(() => {});
};
$("btn-next-step").onclick = () => {
  showStep((current.agenda_index || 0) + 1);
  saveMeeting().catch(() => {});
};
$("btn-prev-ok").onclick = () => {
  current.previous_minutes = "approved";
  saveMeeting();
};
$("btn-prev-fix").onclick = () => {
  current.previous_minutes = "approved_as_corrected";
  current.previous_minutes_note = $("previous_minutes_note").value.trim();
  saveMeeting();
};
$("btn-prev-skip").onclick = () => {
  current.previous_minutes = "not_read";
  saveMeeting();
};
$("btn-add-report").onclick = () => {
  const title = $("report-title").value.trim();
  if (!title) return;
  current.reports = current.reports || [];
  current.reports.push({
    title,
    presenter: $("report-presenter").value.trim(),
    body: $("report-body").value.trim(),
  });
  $("report-title").value = "";
  $("report-presenter").value = "";
  $("report-body").value = "";
  renderLists();
};
$("btn-add-old").onclick = () => {
  const text = $("old-item").value.trim();
  if (!text) return;
  current.old_business = current.old_business || [];
  current.old_business.push(text);
  $("old-item").value = "";
  renderLists();
};
$("btn-add-announce").onclick = () => {
  const text = $("announce-item").value.trim();
  if (!text) return;
  current.announcements = current.announcements || [];
  current.announcements.push(text);
  $("announce-item").value = "";
  renderLists();
};
$("btn-adjourn").onclick = () => {
  if (!$("adjournment").value.trim()) {
    $("adjournment").value = "With no further business, the meeting was adjourned.";
  }
  current.adjournment = $("adjournment").value.trim();
  saveMeeting();
};
$("btn-add-person").onclick = () => {
  const name = $("new-person").value.trim();
  if (!name || !current) return;
  current.roster = current.roster || [];
  if (!current.roster.includes(name)) current.roster.push(name);
  current.guests = current.guests || [];
  if (!current.guests.includes(name)) current.guests.push(name);
  $("new-person").value = "";
  renderPeople();
};
$("btn-1st").onclick = () => {
  pendingRole = "1st";
  $("motion-status").textContent = "Tap who firsted the motion.";
};
$("btn-2nd").onclick = () => {
  pendingRole = "2nd";
  $("motion-status").textContent = "Tap who seconded.";
};
$("btn-yea").onclick = () => {
  const m = currentMotion();
  if (m) {
    m.yeas = (m.yeas || 0) + 1;
    renderMotions();
  }
};
$("btn-nay").onclick = () => {
  const m = currentMotion();
  if (m) {
    m.nays = (m.nays || 0) + 1;
    renderMotions();
  }
};
$("btn-carry").onclick = () => {
  const m = currentMotion();
  if (!m) return;
  if (current.roberts !== false && !m.seconder) {
    $("motion-status").textContent = "Need a second before it can carry.";
    return;
  }
  m.result = "carried";
  $("motion-text").value = "";
  renderMotions();
};
$("btn-fail").onclick = () => {
  const m = currentMotion();
  if (!m) return;
  m.result = "failed";
  $("motion-text").value = "";
  renderMotions();
};
$("btn-takeaway").onclick = () => {
  const text = $("takeaway-text").value.trim();
  if (!text) return;
  current.takeaways = current.takeaways || [];
  current.takeaways.push({ text, owner: $("takeaway-owner").value.trim() });
  $("takeaway-text").value = "";
  renderTakeaways();
};
$("sign-in-photo").onchange = (e) => addPhoto(e.target.files[0], "sign_in");
$("doc-photo").onchange = (e) => addPhoto(e.target.files[0], "document");
$("btn-email").onclick = async () => {
  await saveMeeting();
  const mail = await api(`/api/meetings/${current.id}/email`);
  mailto(mail.subject, mail.body);
};
$("btn-share").onclick = async () => {
  await saveMeeting();
  const mail = await api(`/api/meetings/${current.id}/email`);
  if (navigator.share) {
    await navigator.share({ title: mail.subject, text: mail.body });
    return;
  }
  mailto(mail.subject, mail.body);
};
$("btn-approve").onclick = async () => {
  current.minutes_approved = true;
  await saveMeeting();
  $("save-status").textContent = "Minutes marked approved. Audio may be removed per your retention setting.";
};
$("btn-draft").onclick = async () => {
  await saveMeeting();
  $("save-status").textContent = "This uploads this recording to SpaceXAI…";
  try {
    const data = await api(`/api/meetings/${current.id}/draft`, { method: "POST" });
    $("minutes").textContent = data.markdown;
    $("save-status").textContent = "Draft returned. Edit before you email.";
  } catch (e) {
    $("save-status").textContent = e.message;
  }
};
$("btn-delete").onclick = async () => {
  if (!current || !confirm("Delete this meeting from this device?")) return;
  await api(`/api/meetings/${current.id}`, { method: "DELETE" });
  current = null;
  $("console").hidden = true;
  await refreshList();
};

boot().catch((e) => {
  $("vault-path").textContent = e.message;
});
