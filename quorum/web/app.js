const $ = (id) => document.getElementById(id);

let settings = {};
let current = null;
let rec = { ctx: null, proc: null, stream: null, chunks: [], started: 0, analyser: null, raf: 0 };
let pendingRole = null;
let playbackRate = 1;
let undoStack = [];

function debounce(fn, ms) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), ms);
  };
}

function confirmedRosterNames(draft) {
  const names = [];
  const seen = new Set();
  (draft || []).forEach((row) => {
    const name = String((row && row.name) || "").replace(/\s+/g, " ").trim();
    if (!name) return;
    const key = name.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    names.push(name);
  });
  return names;
}

function confirmedRosterTitles(draft) {
  const titles = {};
  (draft || []).forEach((row) => {
    const name = String((row && row.name) || "").replace(/\s+/g, " ").trim();
    const title = String((row && row.title) || "").replace(/\s+/g, " ").trim();
    if (name && title) titles[name] = title;
  });
  return titles;
}

function rosterTextFromSettings() {
  const names = (settings && settings.roster) || [];
  const titles = (settings && settings.roster_titles) || {};
  const lookup = {};
  Object.entries(titles).forEach(([name, title]) => {
    lookup[String(name).toLowerCase()] = title;
  });
  return names
    .map((name) => {
      const title = lookup[String(name).toLowerCase()] || "";
      return title ? `${title}: ${name}` : name;
    })
    .join("\n");
}

function applyStoredRosterTitles(draft) {
  const titles = (settings && settings.roster_titles) || {};
  const lookup = {};
  Object.entries(titles).forEach(([name, title]) => {
    lookup[String(name).toLowerCase()] = title;
  });
  (draft || []).forEach((row) => {
    if (!row || row.title) return;
    const found = lookup[String(row.name || "").toLowerCase()];
    if (found) row.title = found;
  });
  return draft;
}

function rememberedOfficersFromSettings() {
  if (settings && Object.prototype.hasOwnProperty.call(settings, "officers")) {
    return (settings.officers || [])
      .map((row) => ({
        role: String((row && row.role) || "").replace(/\s+/g, " ").trim(),
        name: String((row && row.name) || "").replace(/\s+/g, " ").trim(),
      }))
      .filter((row) => row.role);
  }
  const titles = (settings && settings.roster_titles) || {};
  const officers = [];
  const seen = new Set();
  Object.entries(titles).forEach(([name, title]) => {
    const role = String(title || "").replace(/\s+/g, " ").trim();
    const person = String(name || "").replace(/\s+/g, " ").trim();
    if (!role || !person || role.toLowerCase() === "member") return;
    const key = role.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    officers.push({ role, name: person });
  });
  return officers;
}

function shouldAskOfficers() {
  if (settings && Object.prototype.hasOwnProperty.call(settings, "officers")) return true;
  return rememberedOfficersFromSettings().length > 0;
}

function titleLookup() {
  const officers = rememberedOfficersFromSettings();
  const managed = new Set(officers.map((row) => row.role.toLowerCase()));
  const lookup = {};
  const add = (name, title, skipManaged) => {
    const person = String(name || "").replace(/\s+/g, " ").trim();
    const role = String(title || "").replace(/\s+/g, " ").trim();
    if (!person || !role) return;
    if (skipManaged && managed.has(role.toLowerCase())) return;
    lookup[person.toLowerCase()] = role;
  };
  Object.entries((settings && settings.roster_titles) || {}).forEach(([name, title]) => add(name, title, true));
  Object.entries((current && current.roster_titles) || {}).forEach(([name, title]) => add(name, title, true));
  officers.forEach((row) => add(row.name, row.role, false));
  return lookup;
}

function titleForName(name) {
  return titleLookup()[String(name || "").toLowerCase()] || "";
}

const SAL_484_TITLES = ["Commander", "1st Vice Commander", "2nd Vice Commander"];
const SAL_484_NOTES = "SAL Post 484: Commander or presiding 1st/2nd Vice + at least 3 other officers";
let wizQuorumExtraTitles = [];
let lastOrgQuorum = null;
let orgQuorumDismissedKey = "";

function selectedQuorumMode() {
  const picked = document.querySelector('input[name="wiz-quorum-mode"]:checked');
  return (picked && picked.value) || "none";
}

function selectedPresidingTitles() {
  return [...document.querySelectorAll("#wiz-quorum-titles input[type=checkbox]:checked")]
    .map((el) => el.value)
    .filter(Boolean);
}

function formatPresidingPhrase(titles) {
  const keys = (titles || []).map((t) => String(t || "").toLowerCase());
  const hasCmd = keys.some((t) => t.includes("commander") && !t.includes("vice"));
  const has1st = keys.some((t) => t.includes("1st") || t.includes("first"));
  const has2nd = keys.some((t) => t.includes("2nd") || t.includes("second"));
  if (hasCmd && has1st && has2nd) return "Commander or 1st/2nd Vice";
  if ((titles || []).length === 1) return titles[0];
  if ((titles || []).length === 2) return `${titles[0]} or ${titles[1]}`;
  if ((titles || []).length > 2) return `${titles.slice(0, -1).join(", ")}, or ${titles[titles.length - 1]}`;
  return "";
}

function previewQuorumRule(rule) {
  if (!rule || rule.mode === "none") return "No special quorum rule.";
  if (rule.mode === "text") return rule.notes || "Check quorum manually.";
  const titles = rule.presiding_any_of || [];
  const phrase = formatPresidingPhrase(titles);
  const minOff = Number(rule.min_other_officers) || 0;
  if (phrase === "Commander or 1st/2nd Vice" && minOff === 3) {
    return "Quorum = Commander or 1st/2nd Vice presiding, plus at least 3 other officers.";
  }
  const bits = [];
  if (phrase) bits.push(`${phrase} presiding`);
  if (minOff) bits.push(`plus at least ${minOff} other officer${minOff === 1 ? "" : "s"}`);
  if (rule.min_members_total) {
    bits.push(`a total of at least ${rule.min_members_total} members present`);
  }
  if (!bits.length) return "No special quorum rule.";
  return `Quorum = ${bits.join(", ")}.`;
}

function readWizardQuorumRule() {
  const mode = selectedQuorumMode();
  if (mode === "text") {
    return {
      mode: "text",
      presiding_any_of: [],
      min_other_officers: 0,
      min_members_total: null,
      notes: ($("wiz-quorum-text") && $("wiz-quorum-text").value.trim()) || "",
    };
  }
  if (mode !== "structured") {
    return {
      mode: "none",
      presiding_any_of: [],
      min_other_officers: 0,
      min_members_total: null,
      notes: "",
    };
  }
  const minOff = Number(($("wiz-quorum-min-officers") && $("wiz-quorum-min-officers").value) || 0);
  const rawTotal = $("wiz-quorum-min-members") ? $("wiz-quorum-min-members").value : "";
  const minTotal = String(rawTotal || "").trim() === "" ? null : Number(rawTotal);
  return {
    mode: "structured",
    presiding_any_of: selectedPresidingTitles(),
    min_other_officers: Number.isFinite(minOff) ? minOff : 0,
    min_members_total: Number.isFinite(minTotal) && minTotal > 0 ? minTotal : null,
    notes: ($("wiz-quorum-struct-notes") && $("wiz-quorum-struct-notes").value) || "",
  };
}

function rosterTitleChoices() {
  const seen = new Set();
  const titles = [];
  const add = (value) => {
    const title = String(value || "").replace(/\s+/g, " ").trim();
    if (!title) return;
    const key = title.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    titles.push(title);
  };
  rememberedOfficersFromSettings().forEach((row) => add(row.role));
  (wizRosterDraft || []).forEach((row) => add(row.title));
  Object.values((settings && settings.roster_titles) || {}).forEach(add);
  ((settings.quorum_rule && settings.quorum_rule.presiding_any_of) || []).forEach(add);
  wizQuorumExtraTitles.forEach(add);
  return titles;
}

function refreshQuorumTitleChoices() {
  const box = $("wiz-quorum-titles");
  if (!box) return;
  const checked = new Set(selectedPresidingTitles().map((t) => t.toLowerCase()));
  box.innerHTML = "";
  rosterTitleChoices().forEach((title) => {
    const label = document.createElement("label");
    label.className = "check";
    const boxEl = document.createElement("input");
    boxEl.type = "checkbox";
    boxEl.value = title;
    boxEl.checked = checked.has(title.toLowerCase());
    boxEl.onchange = updateQuorumPreview;
    label.appendChild(boxEl);
    label.appendChild(document.createTextNode(" " + title));
    box.appendChild(label);
  });
  updateQuorumModePanels();
  updateQuorumPreview();
}

function updateQuorumModePanels() {
  const mode = selectedQuorumMode();
  if ($("wiz-quorum-structured")) $("wiz-quorum-structured").hidden = mode !== "structured";
  if ($("wiz-quorum-text-wrap")) $("wiz-quorum-text-wrap").hidden = mode !== "text";
}

function updateQuorumPreview() {
  const el = $("wiz-quorum-preview");
  if (el) el.textContent = previewQuorumRule(readWizardQuorumRule());
}

function fillWizardQuorum(rule) {
  const data = rule || { mode: "none" };
  const mode = data.mode || "none";
  document.querySelectorAll('input[name="wiz-quorum-mode"]').forEach((el) => {
    el.checked = el.value === mode;
  });
  wizQuorumExtraTitles = [...((data.presiding_any_of || []).map((t) => String(t || "").trim()).filter(Boolean))];
  if ($("wiz-quorum-min-officers")) $("wiz-quorum-min-officers").value = data.min_other_officers || 0;
  if ($("wiz-quorum-min-members")) {
    $("wiz-quorum-min-members").value = data.min_members_total == null ? "" : data.min_members_total;
  }
  if ($("wiz-quorum-struct-notes")) $("wiz-quorum-struct-notes").value = mode === "structured" ? data.notes || "" : "";
  if ($("wiz-quorum-text")) $("wiz-quorum-text").value = mode === "text" ? data.notes || "" : "";
  refreshQuorumTitleChoices();
  const wanted = new Set((data.presiding_any_of || []).map((t) => String(t || "").toLowerCase()));
  document.querySelectorAll("#wiz-quorum-titles input[type=checkbox]").forEach((el) => {
    el.checked = wanted.has(el.value.toLowerCase());
  });
  updateQuorumPreview();
}

function applySal484Example() {
  document.querySelectorAll('input[name="wiz-quorum-mode"]').forEach((el) => {
    el.checked = el.value === "structured";
  });
  SAL_484_TITLES.forEach((title) => {
    if (!wizQuorumExtraTitles.some((t) => t.toLowerCase() === title.toLowerCase())) {
      wizQuorumExtraTitles.push(title);
    }
  });
  if ($("wiz-quorum-min-officers")) $("wiz-quorum-min-officers").value = 3;
  if ($("wiz-quorum-struct-notes")) $("wiz-quorum-struct-notes").value = SAL_484_NOTES;
  refreshQuorumTitleChoices();
  document.querySelectorAll("#wiz-quorum-titles input[type=checkbox]").forEach((el) => {
    if (SAL_484_TITLES.some((t) => t.toLowerCase() === el.value.toLowerCase())) el.checked = true;
  });
  updateQuorumPreview();
}

function renderOrgQuorumBanner(result) {
  const el = $("org-quorum-banner");
  if (!el) return;
  lastOrgQuorum = result || null;
  if (!result) {
    el.hidden = true;
    return;
  }
  const key = `${result.status}|${result.need || ""}|${result.minutes_line || result.banner_title || ""}`;
  if (orgQuorumDismissedKey === key) {
    el.hidden = true;
    return;
  }
  el.hidden = false;
  el.className = "org-quorum-banner " + (result.status || "");
  if ($("org-quorum-title")) $("org-quorum-title").textContent = result.banner_title || "";
  if ($("org-quorum-detail")) $("org-quorum-detail").textContent = result.banner_detail || "";
}

function openQuorumRuleEditor() {
  showWizard(true);
  const section = $("wiz-quorum");
  if (section && section.scrollIntoView) section.scrollIntoView({ block: "start" });
}

function renderRosterConfirm(listId, draft) {
  const list = $(listId);
  if (!list) return;
  list.innerHTML = "";
  (draft || []).forEach((row, index) => {
    const li = document.createElement("li");
    const input = document.createElement("input");
    input.value = row.name || "";
    input.setAttribute("aria-label", "Roster name");
    input.oninput = () => {
      draft[index].name = input.value;
    };
    const title = document.createElement("span");
    title.className = "title";
    title.textContent = row.title || "";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "danger";
    remove.textContent = "Remove";
    remove.onclick = () => {
      draft.splice(index, 1);
      renderRosterConfirm(listId, draft);
    };
    li.appendChild(input);
    li.appendChild(title);
    li.appendChild(remove);
    list.appendChild(li);
  });
}

function showRosterFlags(elId, skipped) {
  const el = $(elId);
  if (!el) return;
  const rows = skipped || [];
  el.textContent = rows.length ? `Skipped: ${rows.map((r) => r.line).join(" · ")}` : "";
}

async function parseRosterText(text) {
  return api("/api/roster/parse", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text: String(text || "") }),
  });
}

let wizRosterDraft = [];
let meetRosterDraft = [];
let officerDraft = [];

function showOfficerSheet() {
  const sheet = $("officer-sheet");
  if (!sheet) return;
  renderOfficerDraft();
  sheet.hidden = false;
}

function hideOfficerSheet() {
  const sheet = $("officer-sheet");
  if (sheet) sheet.hidden = true;
}

function renderOfficerDraft() {
  const list = $("officer-list");
  if (!list) return;
  list.innerHTML = "";
  (officerDraft || []).forEach((row, index) => {
    const li = document.createElement("li");
    const role = document.createElement("span");
    role.className = "role";
    role.textContent = row.role || "";
    const input = document.createElement("input");
    input.value = row.name || "";
    input.setAttribute("aria-label", `${row.role || "Officer"} name`);
    input.placeholder = "Name";
    input.oninput = () => {
      officerDraft[index].name = input.value;
      persistOfficerDraft();
    };
    const vacate = document.createElement("button");
    vacate.type = "button";
    vacate.className = "danger";
    vacate.textContent = "Vacate";
    vacate.onclick = async () => {
      officerDraft[index].name = "";
      renderOfficerDraft();
      try {
        await saveOfficerDraft();
      } catch (e) {
        if ($("officer-error")) $("officer-error").textContent = e.message || "Could not save officers";
      }
    };
    li.appendChild(role);
    li.appendChild(input);
    li.appendChild(vacate);
    list.appendChild(li);
  });
}

const persistOfficerDraft = debounce(() => {
  saveOfficerDraft().catch((e) => {
    if ($("officer-error")) $("officer-error").textContent = e.message || "Could not save officers";
  });
}, 200);

async function saveOfficerDraft() {
  const officers = (officerDraft || [])
    .map((row) => ({
      role: String((row && row.role) || "").replace(/\s+/g, " ").trim(),
      name: String((row && row.name) || "").replace(/\s+/g, " ").trim(),
    }))
    .filter((row) => row.role);
  const data = await api("/api/settings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ officers }),
  });
  settings = data.settings || settings;
  refreshQuorumTitleChoices();
  if (current) renderPeople();
  return officers;
}

function takePendingOfficerAdd() {
  const role = ($("officer-add-role") && $("officer-add-role").value || "").replace(/\s+/g, " ").trim();
  const name = ($("officer-add-name") && $("officer-add-name").value || "").replace(/\s+/g, " ").trim();
  if (!role) return false;
  const key = role.toLowerCase();
  const existing = officerDraft.find((row) => String(row.role || "").toLowerCase() === key);
  if (existing) existing.name = name;
  else officerDraft.push({ role, name });
  if ($("officer-add-role")) $("officer-add-role").value = "";
  if ($("officer-add-name")) $("officer-add-name").value = "";
  return true;
}

async function confirmOfficersAndStart() {
  const err = $("officer-error");
  if (err) err.textContent = "";
  takePendingOfficerAdd();
  await saveOfficerDraft();
  const data = await api("/api/meetings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Regular Meeting" }),
  });
  hideOfficerSheet();
  await openMeeting(data.meeting.id);
}

async function refreshWizardRosterDraft(text) {
  const parsed = await parseRosterText(text);
  wizRosterDraft = (parsed.entries || []).map((entry) => ({
    name: entry.name,
    title: entry.title || "",
    raw: entry.raw || "",
  }));
  applyStoredRosterTitles(wizRosterDraft);
  renderRosterConfirm("wiz-roster-confirm", wizRosterDraft);
  showRosterFlags("wiz-roster-flags", parsed.skipped);
  refreshQuorumTitleChoices();
  return parsed;
}

async function refreshMeetingRosterDraft(text) {
  const parsed = await parseRosterText(text);
  meetRosterDraft = (parsed.entries || []).map((entry) => ({
    name: entry.name,
    title: entry.title || "",
    raw: entry.raw || "",
  }));
  renderRosterConfirm("meet-roster-confirm", meetRosterDraft);
  showRosterFlags("meet-roster-flags", parsed.skipped);
  return parsed;
}

function addDraftName(draft, name) {
  const trimmed = String(name || "").replace(/\s+/g, " ").trim();
  if (!trimmed) return draft;
  const key = trimmed.toLowerCase();
  if (draft.some((row) => String(row.name || "").toLowerCase() === key)) return draft;
  draft.push({ name: trimmed, title: "", raw: trimmed });
  return draft;
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
    documents: [],
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
  renderSigninReview();
  renderDocuments();
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
    const title = titleForName(name);
    b.textContent = title ? `${title}: ${name}` : name;
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

function snapshot() {
  if (!current) return;
  undoStack.push(JSON.stringify(current));
  if (undoStack.length > 30) undoStack.shift();
}

async function undoLast() {
  const raw = undoStack.pop();
  if (!raw || !current) {
    $("save-status").textContent = "Nothing to undo";
    return;
  }
  current = JSON.parse(raw);
  fillHeader();
  renderPeople();
  renderMotions();
  renderTakeaways();
  await saveMeeting();
  $("save-status").textContent = "Undid last change";
}

function onPerson(name) {
  snapshot();
  if (rec.started) {
    const seconds = (Date.now() - rec.started) / 1000;
    current.speaker_marks = current.speaker_marks || [];
    current.speaker_marks.push({ seconds, name });
    if (!(current.present || []).includes(name)) current.present.push(name);
    $("save-status").textContent = `${name} marked speaking`;
    renderPeople();
    updateQuorum();
    persistAttendance();
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
    persistAttendance();
    return;
  }
  const present = new Set(current.present || []);
  if (present.has(name)) present.delete(name);
  else present.add(name);
  current.present = [...present];
  renderPeople();
  updateQuorum();
  persistAttendance();
}

function persistAttendance() {
  if (!current || !current.id) return;
  saveMeeting().catch(() => {});
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
    if (!p.data_url) return;
    const img = document.createElement("img");
    img.src = p.data_url;
    img.alt = p.name;
    box.appendChild(img);
  });
}

function formatDocBytes(n) {
  const size = Number(n) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${Math.round(size / 1024)} KB`;
  return `${(size / (1024 * 1024)).toFixed(1)} MB`;
}

function renderDocuments() {
  const items = current && current.documents ? current.documents : [];
  const html = items.length
    ? items
        .map((d) => {
          const href = current.id
            ? `/api/meetings/${encodeURIComponent(current.id)}/documents/${encodeURIComponent(d.filename)}`
            : "#";
          const when = d.time ? ` · ${d.time}` : "";
          return `<li><a href="${href}" target="_blank" rel="noopener">${d.label || "other"} · ${d.filename} · ${formatDocBytes(d.bytes)}${when}</a></li>`;
        })
        .join("")
    : `<li class="hint">No documents attached</li>`;
  ["doc-list", "doc-list-reports"].forEach((id) => {
    const el = $(id);
    if (el) el.innerHTML = html;
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
  renderDocuments();
  renderSigninReview();
  updateQuorum();
  $("minutes").textContent = data.markdown;
  renderOrgQuorumBanner(data.org_quorum);
  $("player").src = current.has_audio ? `/api/meetings/${id}/audio?t=${Date.now()}` : "";
  $("btn-download").href = `/api/meetings/${id}/minutes.md`;
  $("btn-download").setAttribute("download", `${current.file_stem || id}-minutes.md`);
  $("btn-print").href = `/api/meetings/${id}/print.html`;
  await refreshList();
  syncRecordControls();
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
  renderOrgQuorumBanner(data.org_quorum);
  renderLists();
  showStep(current.agenda_index || 0);
  $("save-status").textContent = `Saved ${new Date().toLocaleTimeString()}`;
  await refreshList();
}

function hasOpenMeeting() {
  return Boolean(current?.id);
}

function syncRecordControls() {
  const recBtn = $("btn-rec");
  const stopBtn = $("btn-stop");
  if (!recBtn || !stopBtn) return;
  const recording = Boolean(rec.started);
  recBtn.disabled = recording || !hasOpenMeeting();
  stopBtn.disabled = !recording;
  if (!recording) recBtn.classList.remove("hot");
  if (!hasOpenMeeting() && !recording) {
    $("meter-label").textContent = "Start meeting first, then Record";
  }
}

function setMeter(level) {
  const fill = $("meter-fill");
  const wrap = fill.parentElement;
  const pct = Math.min(100, Math.round(level * 140));
  fill.style.width = `${pct}%`;
  wrap.className = "meter";
  if (level < 0.04) wrap.classList.add("quiet");
  else if (level > 0.55) wrap.classList.add("hot");
  if (!rec.started && !hasOpenMeeting()) {
    $("meter-label").textContent = "Start meeting first, then Record";
    return;
  }
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
  const outs = devices.filter((d) => d.kind === "audiooutput");
  const spk = $("spk-device");
  if (spk) {
    const prevOut = spk.value;
    spk.innerHTML = "";
    if (!outs.length) {
      const opt = document.createElement("option");
      opt.value = "";
      opt.textContent = "Default speakers";
      spk.appendChild(opt);
    }
    outs.forEach((d, i) => {
      const opt = document.createElement("option");
      opt.value = d.deviceId;
      opt.textContent = d.label || `Speaker ${i + 1}`;
      spk.appendChild(opt);
    });
    if (prevOut && [...spk.options].some((o) => o.value === prevOut)) spk.value = prevOut;
    applySink();
  }
}

function applySink() {
  const player = $("player");
  const id = $("spk-device")?.value;
  if (player && id && typeof player.setSinkId === "function") {
    player.setSinkId(id).catch(() => {});
  }
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
  $("meter-label").textContent = hasOpenMeeting()
    ? "Listening — confirm the meter moves before Record"
    : "Start meeting first, then Record";
  syncRecordControls();
}

async function startRec() {
  if (!hasOpenMeeting()) {
    $("meter-label").textContent = "Start meeting first, then Record";
    syncRecordControls();
    return;
  }
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
  $("btn-rec").classList.remove("hot");
  $("btn-stop").disabled = true;
  $("rec-banner").hidden = true;
  if (!chunks.length) {
    $("meter-label").textContent = "Nothing captured";
    syncRecordControls();
    return;
  }
  if (!hasOpenMeeting()) {
    $("meter-label").textContent = "Start meeting first, then Record";
    syncRecordControls();
    return;
  }
  $("meter-label").textContent = "Saving recording…";
  try {
    const blob = encodeWav(chunks, rate);
    await api(`/api/meetings/${current.id}/audio`, { method: "POST", body: blob });
    $("player").src = `/api/meetings/${current.id}/audio?t=${Date.now()}`;
    current.has_audio = true;
    await saveMeeting();
    $("meter-label").textContent = "Saved recording";
    armMic().catch(() => {});
  } catch (e) {
    $("meter-label").textContent = e.message || "Could not save recording";
  }
  syncRecordControls();
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(file);
  });
}

function renderSigninReview() {
  const box = $("signin-review");
  const names = $("signin-names");
  if (!box || !names || !current) return;
  const hasSheet = (current.photos || []).some((p) => p.kind === "sign_in");
  box.hidden = !hasSheet;
  names.innerHTML = "";
  (current.roster || []).forEach((name) => {
    const label = document.createElement("label");
    label.className = "check";
    const boxEl = document.createElement("input");
    boxEl.type = "checkbox";
    boxEl.value = name;
    boxEl.checked = (current.present || []).includes(name);
    label.appendChild(boxEl);
    label.appendChild(document.createTextNode(" " + name));
    names.appendChild(label);
  });
}

async function addPhoto(file, kind) {
  if (!file || !current) return;
  snapshot();
  const data_url = await fileToDataUrl(file);
  current.photos = current.photos || [];
  current.photos.push({ name: file.name || kind, kind, data_url });
  renderPhotos();
  renderSigninReview();
  await saveMeeting();
}

async function addDocuments(fileList, label) {
  const files = [...(fileList || [])].filter(Boolean);
  if (!files.length) return;
  if (!hasOpenMeeting()) {
    $("save-status").textContent = "Open a meeting first";
    return;
  }
  $("save-status").textContent = "Saving document…";
  try {
    for (const file of files) {
      const params = new URLSearchParams({
        label: label || "other",
        filename: file.name || "document",
      });
      const data = await api(`/api/meetings/${current.id}/documents?${params}`, {
        method: "POST",
        body: file,
      });
      current = data.meeting;
    }
    renderDocuments();
    $("save-status").textContent =
      files.length === 1 ? `Attached ${files[0].name || "document"}` : `Attached ${files.length} documents`;
  } catch (e) {
    $("save-status").textContent = e.message || "Could not save document";
  }
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
  $("wiz-roster").value = rosterTextFromSettings();
  fillWizardQuorum(settings.quorum_rule);
  $("wizard").hidden = false;
  refreshWizardRosterDraft($("wiz-roster").value).catch(() => {
    wizRosterDraft = (settings.roster || []).map((name) => ({
      name,
      title: (settings.roster_titles && settings.roster_titles[name]) || "",
      raw: name,
    }));
    applyStoredRosterTitles(wizRosterDraft);
    renderRosterConfirm("wiz-roster-confirm", wizRosterDraft);
    refreshQuorumTitleChoices();
  });
}

function showBootError(msg) {
  const el = $("boot-error") || $("vault-path") || $("wiz-error");
  if (el) {
    el.hidden = false;
    el.textContent = msg;
  }
}

async function boot() {
  syncRecordControls();
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js").catch(() => {});
  }
  try {
    const status = await api("/api/status");
    settings = status.settings || {};
    const urls = (status.lan_urls || []).join(" · ");
    $("vault-path").textContent = `${status.vault} · retention: ${settings.retention || "until_approved"}${urls ? " · phones: " + urls : ""}`;
    showWizard();
    await refreshList();
    await fillMics().catch(() => {});
    syncRecordControls();
  } catch (e) {
    showBootError(`Quorum is not talking to this page (${e.message}). Use Start Quorum and stay on http://127.0.0.1:4840, then click Hear the room.`);
    showWizard(true);
  }
}

$("btn-wiz-save").onclick = async () => {
  const err = $("wiz-error");
  if (err) err.textContent = "";
  try {
    if (!wizRosterDraft.length && $("wiz-roster").value.trim()) {
      await refreshWizardRosterDraft($("wiz-roster").value);
    }
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
        roster: confirmedRosterNames(wizRosterDraft),
        roster_titles: confirmedRosterTitles(wizRosterDraft),
        quorum_rule: readWizardQuorumRule(),
      }),
    }).then((d) => d.settings);
    $("wizard").hidden = true;
    if ($("vault-path")) $("vault-path").textContent = "Setup saved on this computer.";
    if (current && current.id) persistAttendance();
    else renderOrgQuorumBanner(null);
  } catch (e) {
    if (err) err.textContent = e.message || "Could not save setup";
    else showBootError(e.message || "Could not save setup");
  }
};

$("btn-setup").onclick = () => showWizard(true);
$("wiz-roster").addEventListener(
  "input",
  debounce(() => {
    refreshWizardRosterDraft($("wiz-roster").value).catch(() => {});
  }, 200)
);
$("btn-wiz-roster-add").onclick = () => {
  addDraftName(wizRosterDraft, $("wiz-roster-add-name").value);
  $("wiz-roster-add-name").value = "";
  renderRosterConfirm("wiz-roster-confirm", wizRosterDraft);
  refreshQuorumTitleChoices();
};
document.querySelectorAll('input[name="wiz-quorum-mode"]').forEach((el) => {
  el.onchange = () => {
    updateQuorumModePanels();
    updateQuorumPreview();
  };
});
if ($("btn-wiz-quorum-add-title")) {
  $("btn-wiz-quorum-add-title").onclick = () => {
    const title = ($("wiz-quorum-add-title") && $("wiz-quorum-add-title").value || "").replace(/\s+/g, " ").trim();
    if (!title) return;
    if (!wizQuorumExtraTitles.some((t) => t.toLowerCase() === title.toLowerCase())) {
      wizQuorumExtraTitles.push(title);
    }
    $("wiz-quorum-add-title").value = "";
    refreshQuorumTitleChoices();
    document.querySelectorAll("#wiz-quorum-titles input[type=checkbox]").forEach((box) => {
      if (box.value.toLowerCase() === title.toLowerCase()) box.checked = true;
    });
    updateQuorumPreview();
  };
}
if ($("btn-wiz-quorum-sal")) $("btn-wiz-quorum-sal").onclick = applySal484Example;
["wiz-quorum-min-officers", "wiz-quorum-min-members", "wiz-quorum-struct-notes", "wiz-quorum-text"].forEach((id) => {
  const el = $(id);
  if (el) el.addEventListener("input", updateQuorumPreview);
});
if ($("btn-org-quorum-dismiss")) {
  $("btn-org-quorum-dismiss").onclick = () => {
    const result = lastOrgQuorum || {};
    orgQuorumDismissedKey = `${result.status || ""}|${result.need || ""}|${result.minutes_line || result.banner_title || ""}`;
    if ($("org-quorum-banner")) $("org-quorum-banner").hidden = true;
  };
}
if ($("btn-org-quorum-edit")) $("btn-org-quorum-edit").onclick = openQuorumRuleEditor;
$("btn-demo").onclick = async () => {
  try {
    const data = await api("/api/demo", { method: "POST" });
    await openMeeting(data.meeting.id);
  } catch (e) {
    showBootError(e.message || "Dry-run failed");
  }
};
$("btn-new").onclick = async () => {
  try {
    if (shouldAskOfficers()) {
      officerDraft = rememberedOfficersFromSettings().map((row) => ({ role: row.role, name: row.name }));
      showOfficerSheet();
      return;
    }
    const data = await api("/api/meetings", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Regular Meeting" }),
    });
    await openMeeting(data.meeting.id);
  } catch (e) {
    showBootError(e.message || "Could not start meeting");
  }
};
if ($("btn-officer-confirm")) {
  $("btn-officer-confirm").onclick = () => {
    confirmOfficersAndStart().catch((e) => {
      if ($("officer-error")) $("officer-error").textContent = e.message || "Could not start meeting";
      else showBootError(e.message || "Could not start meeting");
    });
  };
}
if ($("btn-officer-add")) {
  $("btn-officer-add").onclick = async () => {
    if (!takePendingOfficerAdd()) return;
    renderOfficerDraft();
    try {
      await saveOfficerDraft();
    } catch (e) {
      if ($("officer-error")) $("officer-error").textContent = e.message || "Could not save officers";
    }
  };
}
$("btn-save").onclick = () => saveMeeting().catch((e) => { $("save-status").textContent = e.message; });
$("btn-rec").onclick = () => startRec().catch((e) => {
  const msg = String(e.message || e);
  $("meter-label").textContent = /notallowed|permission|denied/i.test(msg)
    ? "Microphone blocked — allow access in the browser, or pick another device"
    : msg;
});
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
if ($("meet-roster-paste")) {
  $("meet-roster-paste").addEventListener(
    "input",
    debounce(() => {
      refreshMeetingRosterDraft($("meet-roster-paste").value).catch(() => {});
    }, 200)
  );
}
if ($("btn-meet-roster-add")) {
  $("btn-meet-roster-add").onclick = () => {
    addDraftName(meetRosterDraft, $("meet-roster-add-name").value);
    $("meet-roster-add-name").value = "";
    renderRosterConfirm("meet-roster-confirm", meetRosterDraft);
  };
}
$("btn-apply-roster").onclick = async () => {
  if (!current) {
    $("save-status").textContent = "Open a meeting first";
    return;
  }
  try {
    if (!meetRosterDraft.length && $("meet-roster-paste").value.trim()) {
      await refreshMeetingRosterDraft($("meet-roster-paste").value);
    }
    const names = confirmedRosterNames(meetRosterDraft);
    if (!names.length) {
      $("save-status").textContent = "Confirm names before adding them to the roster";
      return;
    }
    const data = await api(`/api/meetings/${current.id}/roster`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names, titles: confirmedRosterTitles(meetRosterDraft) }),
    });
    current = data.meeting;
    fillHeader();
    renderPeople();
    $("minutes").textContent = data.markdown;
    renderOrgQuorumBanner(data.org_quorum);
    $("save-status").textContent = `Roster updated (${names.length} confirmed). Not marked present.`;
  } catch (e) {
    $("save-status").textContent = e.message || "Could not update roster";
  }
};
$("btn-1st").onclick = () => {
  snapshot();
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
  snapshot();
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
  snapshot();
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
function bindDocInput(inputId, labelId) {
  const input = $(inputId);
  if (!input) return;
  input.onchange = (e) => {
    const label = ($(labelId) && $(labelId).value) || "other";
    addDocuments(e.target.files, label).finally(() => {
      e.target.value = "";
    });
  };
}
bindDocInput("doc-photo", "doc-label");
bindDocInput("doc-file", "doc-label");
bindDocInput("doc-camera-reports", "doc-label-reports");
bindDocInput("doc-file-reports", "doc-label-reports");
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
$("btn-undo").onclick = () => undoLast().catch((e) => { $("save-status").textContent = e.message; });
$("btn-backup").onclick = async () => {
  const data = await api("/api/backup", { method: "POST" });
  $("save-status").textContent = `Backup ${data.name}`;
  window.location.href = `/api/backups/${encodeURIComponent(data.name)}`;
};
$("restore-file").onchange = async (e) => {
  const file = e.target.files[0];
  if (!file) return;
  const buf = await file.arrayBuffer();
  const res = await fetch("/api/restore", { method: "POST", body: buf });
  const data = await res.json();
  if (!res.ok) throw new Error(data.error || res.statusText);
  $("save-status").textContent = `Restored ${data.files} files`;
  await refreshList();
};
$("btn-apply-signin").onclick = async () => {
  snapshot();
  const names = [...$("signin-names").querySelectorAll("input:checked")].map((el) => el.value);
  const data = await api(`/api/meetings/${current.id}/signin`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ names }),
  });
  current = data.meeting;
  fillHeader();
  renderPeople();
  $("minutes").textContent = data.markdown;
  renderOrgQuorumBanner(data.org_quorum);
  $("save-status").textContent = `Sign-in applied (${(data.signin && data.signin.matched.length) || names.length})`;
};
$("spk-device").onchange = () => applySink();
document.addEventListener("keydown", (event) => {
  if (event.target.matches("input, textarea, select")) return;
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "z") {
    event.preventDefault();
    undoLast();
    return;
  }
  if (event.key === "1") $("btn-1st").click();
  if (event.key === "2") $("btn-2nd").click();
  if (event.key.toLowerCase() === "v") $("btn-carry").click();
});
$("btn-delete").onclick = async () => {
  if (!current || !confirm("Delete this meeting from this device?")) return;
  await api(`/api/meetings/${current.id}`, { method: "DELETE" });
  current = null;
  $("console").hidden = true;
  syncRecordControls();
  await refreshList();
};

boot().catch((e) => {
  showBootError(e.message);
});
