# Frame Art

[![Release](https://img.shields.io/github/v/release/alexbbt/ha-frame-art?label=release)](https://github.com/alexbbt/ha-frame-art/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Home Assistant app (formerly an add-on) for your own Samsung Frame pictures.

The TV keeps every uploaded photo in one pile. It can rotate all of them, or only Favorites. This page adds folders the TV does not have. Play a folder and that set becomes Favorites, which is the set the TV rotates. Remove deletes the picture from the TV.

## Install

This needs **Home Assistant OS** or **Supervised**. Container and Core installs do not have Apps.

[![Add this repository in your Home Assistant](https://my.home-assistant.io/badges/supervisor_add_addon_repository.svg)](https://my.home-assistant.io/redirect/supervisor_add_addon_repository/?repository_url=https%3A%2F%2Fgithub.com%2Falexbbt%2Fha-frame-art)

That opens the add-repository dialog on your own Home Assistant, with this address filled in. To add it yourself:

1. **Settings → Apps → Install app**
2. Open the **⋮** menu at the top right and choose **Repositories**
3. Add `https://github.com/alexbbt/ha-frame-art`
4. Install **Frame Art** and start it
5. Set the TV address in the app options
6. Open **Open Web UI**, or port **8391** on the Home Assistant machine

The first time it connects, accept **Frame Art** on the TV. It runs on 64-bit Home Assistant (aarch64 or amd64).

To pick up a newer version, open the app and choose **Check for updates**.

## What the TV can store

```mermaid
flowchart LR
  PAGE[Folders on this page] --> TV[My Photos on the TV]
  PAGE --> FAV[Favorites]
  FAV --> PLAY[The set that rotates]
```

| On the TV | What it is |
|-----------|------------|
| My Photos | Every picture this page uploads |
| Favorites | The one folder you chose to play |
| Slideshow | Either Favorites, or every photo |

There is no way to create more folders on the TV. Folders in this app are the way to keep sets and play one of them.

## Configuration

| Option | Default | Meaning |
|--------|---------|---------|
| `host` | empty | TV address on your network |
| `port` | `8001` | Art connection port. Use `8002` if the TV requires the encrypted port |
| `token` | empty | Leave empty for the on-screen prompt. Fill it in if the TV already gave this app a token |
| `slideshow_minutes` | `60` | How long each picture stays up |
