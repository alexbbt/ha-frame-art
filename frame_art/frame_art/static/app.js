const albumsEl = document.getElementById("albums");
const photosEl = document.getElementById("photos");
const message = document.getElementById("message");
const drop = document.getElementById("drop");
const input = document.getElementById("files");
const albumName = document.getElementById("album-name");
const folderTitle = document.getElementById("folder-title");

let state = { albums: [], photos: [], playing: null, playing_album_id: null, configured: false };
let selected = "";

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
  if (!response.ok) {
    throw new Error(data.error || "The TV did not accept that");
  }
  return data;
}

function render() {
  const album = currentAlbum();
  selected = album ? album.id : "";
  albumsEl.replaceChildren();
  state.albums.forEach((item) => {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = item.name;
    button.className = "album";
    if (item.id === selected) button.classList.add("selected");
    if (state.playing === "album" && item.id === state.playing_album_id) {
      button.classList.add("playing");
    }
    button.addEventListener("click", () => {
      selected = item.id;
      render();
    });
    albumsEl.appendChild(button);
  });

  folderTitle.textContent = album ? album.name : "Pictures";
  const photos = state.photos.filter((photo) => album && photo.album_id === album.id);
  photosEl.replaceChildren();
  if (!photos.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = "Nothing in this folder";
    photosEl.appendChild(li);
    return;
  }
  photos.forEach((photo) => photosEl.appendChild(row(photo)));
}

function row(photo) {
  const li = document.createElement("li");
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = photo.name;
  li.appendChild(name);

  const actions = document.createElement("span");
  actions.className = "row-actions";

  if (state.albums.length > 1) {
    const select = document.createElement("select");
    state.albums.forEach((album) => {
      const option = document.createElement("option");
      option.value = album.id;
      option.textContent = album.name;
      option.selected = album.id === photo.album_id;
      select.appendChild(option);
    });
    select.addEventListener("change", () => move(photo.id, select.value));
    actions.appendChild(select);
  }

  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "Remove";
  remove.addEventListener("click", () => removePhoto(photo));
  actions.appendChild(remove);
  li.appendChild(actions);
  return li;
}

async function refresh() {
  const response = await fetch("api/status");
  state = await response.json();
  if (!state.configured) {
    note("Set the TV address in the app options.", true);
  }
  render();
}

async function send(files) {
  const album = currentAlbum();
  if (!album) return;
  const body = new FormData();
  Array.from(files).forEach((file) => body.append("file", file));
  note("Sending to the TV…", false);
  const response = await fetch("upload?album=" + encodeURIComponent(album.id), {
    method: "POST",
    body,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    note(data.error || "Could not save that picture", true);
    await refresh();
    return;
  }
  note("Saved on the TV.", false);
  await refresh();
}

async function removePhoto(photo) {
  if (!window.confirm("Remove " + photo.name + " from the TV?")) return;
  note("Removing from the TV…", false);
  try {
    await api("api/remove", { id: photo.id });
    note("Removed from the TV.", false);
  } catch (err) {
    note(err.message, true);
  }
  await refresh();
}

async function move(id, albumId) {
  try {
    await api("api/move", { id, album_id: albumId });
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
}

document.getElementById("new-album").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const data = await api("api/albums", { name: albumName.value });
    albumName.value = "";
    selected = data.album.id;
    note("", false);
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

document.getElementById("play").addEventListener("click", async () => {
  const album = currentAlbum();
  if (!album) return;
  note("Setting this folder on the TV…", false);
  try {
    const data = await api("api/play", { album_id: album.id });
    note(data.message || "Playing " + album.name + ".", false);
  } catch (err) {
    note(err.message, true);
  }
  await refresh();
});

document.getElementById("play-all").addEventListener("click", async () => {
  note("Setting every photo to rotate…", false);
  try {
    await api("api/play", { album_id: "" });
    note("Playing every photo.", false);
  } catch (err) {
    note(err.message, true);
  }
  await refresh();
});

document.getElementById("rename").addEventListener("click", async () => {
  const album = currentAlbum();
  if (!album) return;
  const name = window.prompt("Rename folder", album.name);
  if (!name || name === album.name) return;
  try {
    await api("api/albums/rename", { id: album.id, name });
    await refresh();
  } catch (err) {
    note(err.message, true);
  }
});

document.getElementById("delete-folder").addEventListener("click", async () => {
  const album = currentAlbum();
  if (!album) return;
  if (!window.confirm("Delete " + album.name + "? Pictures stay on the TV and move to another folder.")) return;
  try {
    await api("api/albums/delete", { id: album.id });
    selected = "";
    note("Folder deleted.", false);
  } catch (err) {
    note(err.message, true);
  }
  await refresh();
});

document.getElementById("sync").addEventListener("click", async () => {
  const album = currentAlbum();
  if (!album) return;
  note("Reading the TV…", false);
  try {
    await api("api/sync", { album_id: album.id });
    note("Updated from the TV.", false);
  } catch (err) {
    note(err.message, true);
  }
  await refresh();
});

albumsEl.addEventListener("dblclick", () => {
  document.getElementById("rename").click();
});

drop.addEventListener("click", () => input.click());
input.addEventListener("change", () => {
  if (input.files && input.files.length) send(input.files);
  input.value = "";
});
["dragover", "dragenter"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.add("over");
  });
});
["dragleave", "drop"].forEach((name) => {
  drop.addEventListener(name, (event) => {
    event.preventDefault();
    drop.classList.remove("over");
  });
});
drop.addEventListener("drop", (event) => {
  if (event.dataTransfer && event.dataTransfer.files.length) {
    send(event.dataTransfer.files);
  }
});

refresh().catch(() => note("The page could not load the albums.", true));
