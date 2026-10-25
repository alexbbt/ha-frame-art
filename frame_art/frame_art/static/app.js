const albumsEl = document.getElementById("albums");
const titleEl = document.getElementById("title");
const statusEl = document.getElementById("status");
const gridEl = document.getElementById("grid");
const message = document.getElementById("message");
const drop = document.getElementById("drop");
const input = document.getElementById("files");
const addLabel = document.getElementById("add-label");
const minutesEl = document.getElementById("minutes");
const orderEl = document.getElementById("order");
const rotateEl = document.getElementById("rotate");
const frameEl = document.getElementById("frame");
const sheet = document.getElementById("sheet");
const sheetImage = document.getElementById("sheet-image");
const sheetName = document.getElementById("sheet-name");
const sheetMove = document.getElementById("sheet-move");

const STAY = [
  [5, "5 minutes"],
  [15, "15 minutes"],
  [30, "30 minutes"],
  [60, "1 hour"],
  [180, "3 hours"],
  [360, "6 hours"],
  [720, "12 hours"],
  [1440, "1 day"],
];

let state = { albums: [], photos: [], playing: null, playing_album_id: null, configured: true };
let controls = null;
let selected = "";
let sending = false;
let wakeHold = 0;
let wakeSentinel = null;
let wakeAcquiring = false;
let wakeVisibilityListening = false;

function notifyKeepAwake(enabled) {
  try {
    const handler = window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers["keep-awake"];
    if (handler && handler.postMessage) handler.postMessage({ enabled: Boolean(enabled) });
  } catch (err) {
    // The iOS app bridge is optional.
  }
  try {
    if (window.parent !== window) {
      window.parent.postMessage({ type: "bell-towne:keep-awake", enabled: Boolean(enabled) }, "*");
    }
  } catch (err) {
    // A parent frame is optional.
  }
}

async function requestWakeLock() {
  if (wakeHold <= 0 || wakeAcquiring) return;
  notifyKeepAwake(true);
  if (!navigator.wakeLock || !navigator.wakeLock.request) return;
  if (wakeSentinel && !wakeSentinel.released) return;
  if (document.visibilityState !== "visible") return;
  wakeAcquiring = true;
  try {
    wakeSentinel = await navigator.wakeLock.request("screen");
    wakeSentinel.addEventListener("release", () => {
      wakeSentinel = null;
    });
  } catch (err) {
    wakeSentinel = null;
  } finally {
    wakeAcquiring = false;
  }
}

function releaseWakeLock() {
  notifyKeepAwake(false);
  const current = wakeSentinel;
  wakeSentinel = null;
  if (!current) return;
  current.release().catch(() => {});
}

function syncWakeLock(shouldHold) {
  if (shouldHold) {
    if (wakeHold === 0) {
      wakeHold = 1;
      if (!wakeVisibilityListening) {
        document.addEventListener("visibilitychange", () => {
          if (document.visibilityState === "visible" && wakeHold > 0) requestWakeLock();
        });
        wakeVisibilityListening = true;
      }
      requestWakeLock();
    }
    return;
  }
  if (wakeHold > 0) {
    wakeHold = 0;
    releaseWakeLock();
  }
}

window.addEventListener("pagehide", () => syncWakeLock(false));
let applying = false;
let openPhoto = null;
let selecting = false;
let picked = new Set();
let anchor = "";
let ready = new Set();
let loadingPreviews = false;
let warmToken = 0;

function note(text, isError) {
  message.hidden = !text;
  message.textContent = text || "";
  message.classList.toggle("error", Boolean(isError));
}

function currentAlbum() {
  const chosen = state.albums.find((album) => album.id === selected);
  if (chosen) return chosen;
  if (state.playing === "album") {
    const playing = state.albums.find((album) => album.id === state.playing_album_id);
    if (playing) return playing;
  }
  return state.albums[0];
}

async function api(path, payload) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "The TV did not accept that");
  return data;
}

function fillStay(current) {
  const values = STAY.map(([value]) => value);
  minutesEl.replaceChildren();
  const options = values.includes(current) ? STAY : [[current, current + " minutes"], ...STAY];
  options.forEach(([value, label]) => {
    const option = document.createElement("option");
    option.value = String(value);
    option.textContent = label;
    minutesEl.appendChild(option);
  });
  if (current) minutesEl.value = String(current);
}

function needsThumb(photo) {
  if (!photo.content_id || photo.file || String(photo.content_id).startsWith("SAM-S")) return false;
  return !ready.has(photo.content_id);
}

function needsPreviews(album) {
  if (!album) return false;
  return state.photos.some((photo) => photo.album_id === album.id && needsThumb(photo));
}

function render() {
  const album = currentAlbum();
  selected = album ? album.id : "";
  titleEl.textContent = album ? album.name : "Photos";
  if (loadingPreviews) statusEl.textContent = "Loading previews";
  else if (state.playing === "all") statusEl.textContent = "Every photo is rotating";
  else if (state.playing === "album" && state.playing_album_id === selected) statusEl.textContent = "This folder is rotating";
  else statusEl.textContent = "Not rotating";

  albumsEl.replaceChildren();
  state.albums.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "album" + (item.id === selected ? " current" : "");
    button.textContent = item.name;
    button.addEventListener("click", () => {
      if (item.id === selected) return;
      selected = item.id;
      selecting = false;
      picked.clear();
      anchor = "";
      showCurrent();
    });
    albumsEl.appendChild(button);
  });
  document.getElementById("delete-folder").hidden = state.albums.length < 2;

  const photos = state.photos.filter((photo) => album && photo.album_id === album.id);
  const countEl = document.getElementById("select-count");
  const deleteEl = document.getElementById("select-delete");
  const toggleEl = document.getElementById("select-toggle");
  const alive = new Set(photos.map((photo) => photo.id));
  picked = new Set([...picked].filter((id) => alive.has(id)));
  toggleEl.textContent = selecting ? "Cancel" : "Select";
  document.getElementById("select-all").hidden = !selecting || !photos.some((photo) => !photo.preview);
  countEl.hidden = !selecting;
  deleteEl.hidden = !selecting;
  countEl.textContent = picked.size === 1 ? "1 selected" : picked.size + " selected";
  deleteEl.disabled = picked.size === 0;
  document.getElementById("send-tv").hidden = !photos.some((photo) => photo.file && !photo.content_id);
  gridEl.replaceChildren();
  if (!photos.length) {
    const empty = document.createElement("p");
    empty.className = "empty";
    empty.textContent = "Nothing here yet.";
    gridEl.appendChild(empty);
  } else {
    photos.forEach((photo) => gridEl.appendChild(card(photo)));
  }

  applying = true;
  frameEl.value = state.frame === "fill" ? "fill" : "fit";
  if (state.playing === "all") rotateEl.value = "all";
  else if (state.playing === "album" && state.playing_album_id === selected) rotateEl.value = "folder";
  else rotateEl.value = "";
  applying = false;
}

function card(photo) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "card" + (selecting ? " picking" : "") + (picked.has(photo.id) ? " chosen" : "");
  if (selecting) button.setAttribute("aria-pressed", picked.has(photo.id) ? "true" : "false");
  const thumb = document.createElement("div");
  thumb.className = "thumb";
  const store = photo.content_id && String(photo.content_id).startsWith("SAM-S");
  if (photo.preview) {
    thumb.style.backgroundImage = "url('" + photo.preview + "')";
  } else if (photo.file) {
    thumb.style.backgroundImage = "url('file/" + encodeURIComponent(photo.id) + "')";
  } else if (photo.content_id && ready.has(photo.content_id)) {
    thumb.style.backgroundImage = "url('thumb/" + encodeURIComponent(photo.content_id) + "')";
  } else if (loadingPreviews && needsThumb(photo)) {
    thumb.classList.add("waiting");
  }
  const caption = document.createElement("span");
  caption.textContent = photo.name;
  button.append(thumb, caption);
  if (photo.preview || store || (photo.file && !photo.content_id)) {
    const hint = document.createElement("span");
    hint.className = "hint";
    hint.textContent = photo.preview ? "Saving" : store ? "Art Store" : "Not on the TV";
    button.append(hint);
  }
  button.addEventListener("click", (event) => {
    if (photo.preview) return;
    if (!selecting) {
      openSheet(photo);
      return;
    }
    const ids = folderPhotos().map((item) => item.id);
    if (event.shiftKey && anchor && ids.includes(anchor)) {
      event.preventDefault();
      const start = ids.indexOf(anchor);
      const end = ids.indexOf(photo.id);
      const from = Math.min(start, end);
      const to = Math.max(start, end);
      for (let index = from; index <= to; index += 1) picked.add(ids[index]);
    } else if (picked.has(photo.id)) {
      picked.delete(photo.id);
    } else {
      picked.add(photo.id);
    }
    anchor = photo.id;
    render();
  });
  return button;
}

function folderPhotos() {
  const album = currentAlbum();
  return state.photos.filter((photo) => album && photo.album_id === album.id && !photo.preview);
}

function openSheet(photo) {
  openPhoto = photo;
  sheetName.textContent = photo.name;
  if (photo.file) sheetImage.src = "file/" + encodeURIComponent(photo.id);
  else sheetImage.src = photo.content_id ? "thumb/" + encodeURIComponent(photo.content_id) : "";
  document.getElementById("sheet-remove").textContent = photo.content_id ? "Remove from the TV" : "Remove";
  sheetMove.replaceChildren();
  state.albums.forEach((album) => {
    const option = document.createElement("option");
    option.value = album.id;
    option.textContent = album.name;
    option.selected = album.id === photo.album_id;
    sheetMove.appendChild(option);
  });
  sheet.showModal();
}

async function warm(albumId) {
  if (!albumId) return;
  const response = await fetch("api/previews?album=" + encodeURIComponent(albumId), {
    signal: AbortSignal.timeout(20000),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) return;
  (data.ready || []).forEach((id) => ready.add(id));
}

async function showCurrent() {
  const token = ++warmToken;
  const album = currentAlbum();
  loadingPreviews = needsPreviews(album);
  render();
  if (!album || !loadingPreviews) return;
  try {
    await warm(album.id);
  } catch (err) {
    // The names stay up when previews are slow or missing.
  }
  if (token !== warmToken) return;
  loadingPreviews = false;
  render();
}

async function refresh() {
  const response = await fetch("api/status");
  state = await response.json();
  if (!state.configured) note("Set the TV address in the app options.", true);
  await showCurrent();
}

async function loadControls() {
  const response = await fetch("api/settings");
  if (!response.ok) return;
  controls = await response.json();
  const slide = controls.slideshow || {};
  const art = controls.art || {};
  applying = true;
  fillStay(slide.minutes || 60);
  orderEl.value = slide.shuffle ? "shuffle" : "order";
  setArt("brightness", art.brightness, "row-brightness");
  setArt("color", art.color_temperature, "row-color");
  setSelect("motion", art.motion_sensitivity, "row-motion");
  setSelect("sensor", art.brightness_sensor, "row-sensor");
  setSelect("sleep", art.motion_timer, "row-sleep");
  applying = false;
}

function setArt(id, value, rowId) {
  const row = document.getElementById(rowId);
  const input = document.getElementById(id);
  if (value === undefined || value === "") {
    row.hidden = true;
    return;
  }
  row.hidden = false;
  input.value = value;
}

function setSelect(id, value, rowId) {
  const row = document.getElementById(rowId);
  const input = document.getElementById(id);
  if (value === undefined || value === "") {
    row.hidden = true;
    return;
  }
  row.hidden = false;
  input.value = value;
}

async function saveSlideshow() {
  if (applying || !controls) return;
  const data = await api("api/settings", {
    minutes: Number(minutesEl.value),
    shuffle: orderEl.value === "shuffle",
    category_id: (controls.slideshow || {}).category_id,
  });
  controls = data;
}

async function saveArt(item, value) {
  if (applying) return;
  controls = await api("api/settings", { item, value });
}

document.getElementById("new-folder").addEventListener("click", async () => {
  const name = window.prompt("Folder name");
  if (!name) return;
  try {
    const data = await api("api/albums", { name });
    selected = data.album.id;
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

document.getElementById("delete-folder").addEventListener("click", async () => {
  const album = currentAlbum();
  if (!album || !window.confirm("Delete " + album.name + "? The pictures stay on the TV.")) return;
  try {
    await api("api/albums/delete", { id: album.id });
    selected = "";
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

minutesEl.addEventListener("change", () => saveSlideshow().catch((err) => note(err.message, true)));
orderEl.addEventListener("change", () => saveSlideshow().catch((err) => note(err.message, true)));
frameEl.addEventListener("change", async () => {
  if (applying) return;
  try {
    const data = await api("api/frame", { mode: frameEl.value });
    state.frame = data.frame;
  } catch (err) {
    note(err.message, true);
  }
});

rotateEl.addEventListener("change", async () => {
  if (applying) return;
  const album = currentAlbum();
    try {
    if (!rotateEl.value) await api("api/play", { stop: true });
    else if (rotateEl.value === "folder" && album) {
      await api("api/play", {
        album_id: album.id,
        minutes: Number(minutesEl.value),
        shuffle: orderEl.value === "shuffle",
      });
    } else if (rotateEl.value === "all") {
      await api("api/play", {
        album_id: "",
        minutes: Number(minutesEl.value),
        shuffle: orderEl.value === "shuffle",
      });
    }
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

document.getElementById("brightness").addEventListener("change", (event) => {
  saveArt("brightness", event.target.value).catch((err) => note(err.message, true));
});
document.getElementById("color").addEventListener("change", (event) => {
  saveArt("color_temperature", event.target.value).catch((err) => note(err.message, true));
});
document.getElementById("motion").addEventListener("change", (event) => {
  saveArt("motion_sensitivity", event.target.value).catch((err) => note(err.message, true));
});
document.getElementById("sensor").addEventListener("change", (event) => {
  saveArt("brightness_sensor", event.target.value).catch((err) => note(err.message, true));
});
document.getElementById("sleep").addEventListener("change", (event) => {
  saveArt("motion_timer", event.target.value).catch((err) => note(err.message, true));
});

sheetMove.addEventListener("change", async () => {
  if (!openPhoto || sheetMove.value === openPhoto.album_id) return;
  try {
    await api("api/move", { id: openPhoto.id, album_id: sheetMove.value });
    sheet.close();
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

document.getElementById("send-tv").addEventListener("click", async () => {
  const album = currentAlbum();
  const button = document.getElementById("send-tv");
  if (!album || button.disabled) return;
  button.disabled = true;
  try {
    const data = await api("api/send", { album_id: album.id });
    const sent = (data.sent || []).length;
    const waiting = (data.waiting || []).length;
    if (!waiting) note(sent === 1 ? "Sent to the TV." : "Sent " + sent + " pictures.", false);
    else note((sent ? "Sent " + sent + ". " : "") + ((data.waiting[0] && data.waiting[0].error) || "The TV did not take them."), true);
    await refresh();
  } catch (err) {
    note(err.message, true);
  } finally {
    button.disabled = false;
  }
});

document.getElementById("select-toggle").addEventListener("click", () => {
  selecting = !selecting;
  if (!selecting) {
    picked.clear();
    anchor = "";
  }
  render();
});

document.getElementById("select-all").addEventListener("click", () => {
  folderPhotos().forEach((photo) => picked.add(photo.id));
  render();
});

document.getElementById("select-delete").addEventListener("click", async () => {
  const ids = [...picked];
  if (!ids.length) return;
  const label = ids.length === 1 ? "this picture" : ids.length + " pictures";
  if (!window.confirm("Remove " + label + " from the TV?")) return;
  try {
    await api("api/remove", { ids });
    selecting = false;
    picked.clear();
    anchor = "";
    note(ids.length === 1 ? "Removed from the TV." : "Removed " + ids.length + " pictures.", false);
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

document.getElementById("sheet-remove").addEventListener("click", async () => {
  if (!openPhoto) return;
  try {
    await api("api/remove", { id: openPhoto.id });
    sheet.close();
    note("Removed from the TV.", false);
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

function showIncoming(album, file, label) {
  const photo = {
    id: "incoming-" + Math.random().toString(36).slice(2),
    album_id: album.id,
    name: label,
    content_id: "",
    file: false,
    preview: URL.createObjectURL(file),
  };
  state.photos.unshift(photo);
  render();
  const shown = gridEl.querySelector(".card");
  if (shown) shown.scrollIntoView({ block: "nearest" });
  return photo;
}

function forgetIncoming(photo) {
  if (!photo) return;
  if (photo.preview) URL.revokeObjectURL(photo.preview);
  state.photos = state.photos.filter((item) => item.id !== photo.id);
}

async function send(files) {
  const album = currentAlbum();
  const list = Array.from(files || []);
  if (!album || !list.length) return;
  const failed = [];
  let saved = 0;
  let waiting = 0;
  for (let index = 0; index < list.length; index += 1) {
    const file = list[index];
    const label = file.name || "picture";
    addLabel.textContent = "Saving " + (index + 1) + " of " + list.length;
    const incoming = showIncoming(album, file, label);
    try {
      const body = new FormData();
      body.append("file", file, label);
      const response = await fetch("upload?album=" + encodeURIComponent(album.id), { method: "POST", body });
      const data = await response.json().catch(() => ({}));
      forgetIncoming(incoming);
      if (!response.ok) {
        failed.push(label + ": " + (data.error || "Could not save that picture"));
        render();
        continue;
      }
      saved += (data.saved || []).length;
      waiting += (data.waiting || []).length;
      (data.failed || []).forEach((item) => failed.push((item.name || label) + ": " + item.error));
      (data.photos || []).forEach((photo) => {
        if (!state.photos.some((item) => item.id === photo.id)) state.photos.unshift(photo);
      });
      render();
    } catch (err) {
      forgetIncoming(incoming);
      render();
      failed.push(label + ": the phone lost the connection");
      break;
    }
  }
  addLabel.textContent = "Add photos";
  state.photos.forEach((photo) => {
    if (photo.preview) URL.revokeObjectURL(photo.preview);
  });
  await refresh().catch(() => {});
  if (!failed.length && !waiting) note("Saved " + saved + (saved === 1 ? " picture." : " pictures."), false);
  else {
    const held = waiting ? waiting + (waiting === 1 ? " still needs the TV. " : " still need the TV. ") : "";
    note((saved ? "Saved " + saved + ". " : "") + held + failed.slice(0, 2).join(" "), true);
  }
}

async function take(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length || sending) return;
  sending = true;
  syncWakeLock(true);
  drop.classList.add("busy");
  try {
    await send(files);
  } finally {
    sending = false;
    syncWakeLock(false);
    drop.classList.remove("busy");
    input.value = "";
  }
}

input.addEventListener("change", () => take(input.files));

const themeButtons = Array.from(document.querySelectorAll(".appearance button"));
const themeQuery = window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme() {
  try {
    const value = localStorage.getItem("frame-art-theme");
    if (value === "light" || value === "dark" || value === "auto") return value;
  } catch (err) {
    // Private browsing can block storage.
  }
  return "auto";
}

function applyTheme(theme) {
  const choice = theme === "light" || theme === "dark" ? theme : "auto";
  if (choice === "auto") delete document.documentElement.dataset.theme;
  else document.documentElement.dataset.theme = choice;
  const dark = choice === "dark" || (choice === "auto" && themeQuery.matches);
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", dark ? "#111111" : "#ffffff");
  themeButtons.forEach((button) => {
    button.setAttribute("aria-pressed", String(button.dataset.theme === choice));
  });
  try {
    localStorage.setItem("frame-art-theme", choice);
  } catch (err) {
    // The choice still applies for this visit.
  }
}

themeButtons.forEach((button) => {
  button.addEventListener("click", () => applyTheme(button.dataset.theme));
});
themeQuery.addEventListener("change", () => {
  if (savedTheme() === "auto") applyTheme("auto");
});
applyTheme(savedTheme());

fillStay(60);
refresh()
  .then(() => loadControls())
  .catch(() => note("The page could not load.", true));
