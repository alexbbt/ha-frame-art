# Frame Art

[![Release](https://img.shields.io/github/v/release/alexbbt/ha-frame-art?label=release)](https://github.com/alexbbt/ha-frame-art/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Home Assistant app (formerly an add-on) with a web page for your own Samsung Frame pictures.

Drop JPEG, PNG, WebP, or iPhone photos on the page. They are saved into a folder on Home Assistant. An automation can send that folder to the TV's Art Mode, with no Samsung account and no Art Store.

## Install

This needs **Home Assistant OS** or **Supervised**. Container and Core installs do not have Apps.

[![Add this repository in your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Falexbbt%2Fha-frame-art)

That opens the add-repository dialog on your own Home Assistant, with this address filled in. To add it yourself:

1. **Settings → Apps → Install app**
2. Open the **⋮** menu at the top right and choose **Repositories**
3. Add `https://github.com/alexbbt/ha-frame-art`
4. Install **Frame Art** and start it
5. Open **Open Web UI**, or port **8391** on the Home Assistant machine

It runs on 64-bit Home Assistant (aarch64 or amd64).

To pick up a newer version, open the app and choose **Check for updates**.

## How a picture gets to the TV

```mermaid
flowchart LR
  PAGE[This page] --> INBOX[Inbox folder]
  INBOX --> HA[Your automation]
  HA --> TV[Frame Art Mode]
```

This app does not talk to the TV itself. It only fills the inbox. The default folders are:

| Folder | Path |
|--------|------|
| New pictures | `/homeassistant/www/frame-art/inbox` |
| Already sent | `/homeassistant/www/frame-art/uploaded` |

Inside the Home Assistant container those are `/config/www/frame-art/inbox` and `/config/www/frame-art/uploaded`.

A picture leaves the waiting list when something else moves it from the inbox into the uploaded folder.

## Configuration

| Option | Default | Meaning |
|--------|---------|---------|
| `inbox` | `/homeassistant/www/frame-art/inbox` | Where uploads are written |
| `uploaded` | `/homeassistant/www/frame-art/uploaded` | Shown on the page as already sent |
