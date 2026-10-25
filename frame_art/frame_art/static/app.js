const drop = document.getElementById("drop");
const input = document.getElementById("files");
const message = document.getElementById("message");
const inbox = document.getElementById("inbox");
const uploaded = document.getElementById("uploaded");

function note(text, isError) {
  message.hidden = !text;
  message.textContent = text || "";
  message.classList.toggle("error", Boolean(isError));
}

function row(item, canRemove) {
  const li = document.createElement("li");
  const name = document.createElement("span");
  name.className = "name";
  name.textContent = item.name;
  li.appendChild(name);
  if (canRemove) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = "Remove";
    button.addEventListener("click", () => remove(item.name));
    li.appendChild(button);
  }
  return li;
}

function fill(list, items, canRemove, emptyText) {
  list.replaceChildren();
  if (!items.length) {
    const li = document.createElement("li");
    li.className = "empty";
    li.textContent = emptyText;
    list.appendChild(li);
    return;
  }
  items.forEach((item) => list.appendChild(row(item, canRemove)));
}

async function refresh() {
  const response = await fetch("api/status");
  const data = await response.json();
  fill(inbox, data.inbox || [], true, "Nothing waiting");
  fill(uploaded, data.uploaded || [], false, "Nothing sent yet");
}

async function send(files) {
  const body = new FormData();
  Array.from(files).forEach((file) => body.append("file", file));
  note("Sending…", false);
  const response = await fetch("upload", { method: "POST", body });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    note(data.error || "Could not save that picture", true);
    return;
  }
  note("On its way to the TV.", false);
  await refresh();
}

async function remove(name) {
  const response = await fetch("delete", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    note(data.error || "Could not remove that picture", true);
    return;
  }
  note("", false);
  await refresh();
}

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

refresh().catch(() => note("The page could not load the picture list.", true));
