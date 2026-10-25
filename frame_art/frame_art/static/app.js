const folderEl = document.getElementById("folder");
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
let applying = false;
let openPhoto = null;
let ready = new Set();

function note(text, isError) {
  message.hidden = !text;
  message.textContent = text || "";
  message.classList.toggle("error", Boolean(isError));
}

function currentAlbum() {
  return state.albums.find((album) => album.id === selected) || state.albums[0];
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

function render() {
  const album = currentAlbum();
  selected = album ? album.id : "";
  titleEl.textContent = album ? album.name : "Photos";
  if (state.playing === "all") statusEl.textContent = "Every photo is rotating";
  else if (state.playing === "album" && state.playing_album_id === selected) statusEl.textContent = "This folder is rotating";
  else statusEl.textContent = "Not rotating";

  folderEl.replaceChildren();
  state.albums.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.id;
    option.textContent = item.name;
    option.selected = item.id === selected;
    folderEl.appendChild(option);
  });
  document.getElementById("delete-folder").hidden = state.albums.length < 2;

  const photos = state.photos.filter((photo) => album && photo.album_id === album.id);
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
  if (state.playing === "all") rotateEl.value = "all";
  else if (state.playing === "album" && state.playing_album_id === selected) rotateEl.value = "folder";
  else rotateEl.value = "";
  applying = false;
}

function card(photo) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "card";
  const thumb = document.createElement("div");
  thumb.className = "thumb";
  if (photo.content_id && ready.has(photo.content_id)) {
    thumb.style.backgroundImage = "url('thumb/" + encodeURIComponent(photo.content_id) + "')";
  }
  const caption = document.createElement("span");
  caption.textContent = photo.name;
  button.append(thumb, caption);
  button.addEventListener("click", () => openSheet(photo));
  return button;
}

function openSheet(photo) {
  openPhoto = photo;
  sheetName.textContent = photo.name;
  sheetImage.src = photo.content_id ? "thumb/" + encodeURIComponent(photo.content_id) : "";
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
  const response = await fetch("api/previews?album=" + encodeURIComponent(albumId));
  const data = await response.json().catch(() => ({}));
  if (!response.ok) return;
  (data.ready || []).forEach((id) => ready.add(id));
}

async function refresh() {
  const response = await fetch("api/status");
  state = await response.json();
  if (!state.configured) note("Set the TV address in the app options.", true);
  const album = currentAlbum();
  if (album) await warm(album.id).catch(() => {});
  render();
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

folderEl.addEventListener("change", async () => {
  selected = folderEl.value;
  await warm(selected).catch(() => {});
  render();
});

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

async function send(files) {
  const album = currentAlbum();
  const list = Array.from(files || []);
  if (!album || !list.length) return;
  const failed = [];
  let saved = 0;
  for (let index = 0; index < list.length; index += 1) {
    const file = list[index];
    const label = file.name || "picture";
    addLabel.textContent = "Saving " + (index + 1) + " of " + list.length;
    try {
      const body = new FormData();
      body.append("file", file, label);
      const response = await fetch("upload?album=" + encodeURIComponent(album.id), { method: "POST", body });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) {
        failed.push(label + ": " + (data.error || "Could not save that picture"));
        continue;
      }
      saved += (data.saved || []).length;
      (data.failed || []).forEach((item) => failed.push((item.name || label) + ": " + item.error));
    } catch (err) {
      failed.push(label + ": the phone lost the connection");
      break;
    }
  }
  addLabel.textContent = "Add photos";
  await refresh().catch(() => {});
  if (!failed.length) note("Saved " + saved + (saved === 1 ? " picture." : " pictures."), false);
  else note((saved ? "Saved " + saved + ". " : "") + failed.slice(0, 2).join(" "), true);
}

async function take(fileList) {
  const files = Array.from(fileList || []);
  if (!files.length || sending) return;
  sending = true;
  drop.classList.add("busy");
  try {
    await send(files);
  } finally {
    sending = false;
    drop.classList.remove("busy");
    input.value = "";
  }
}

input.addEventListener("change", () => take(input.files));

fillStay(60);
refresh()
  .then(() => loadControls())
  .catch(() => note("The page could not load.", true));
