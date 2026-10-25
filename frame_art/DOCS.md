# Frame Art

## About

Web page for your own pictures on a Samsung Frame. Upload and delete pictures on the TV, sort them into folders, and choose which folder plays.

The TV stores uploads in My Photos and can rotate either all of those photos or only Favorites. Playing a folder here puts that folder into Favorites and rotates only that set.

This is a Home Assistant app (formerly an add-on) for Home Assistant OS or Supervised.

## Page

Open **Open Web UI**, or port **8391** on the Home Assistant machine.

The page accepts JPEG, PNG, WebP, and HEIC. HEIC is converted to JPEG. Pictures are fit onto a 3840x2160 frame. Pictures larger than 40 MB are refused.

The first connection asks you to allow **Frame Art** on the TV.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `host` | empty | Address of the Frame |
| `port` | `8001` | Art connection port |
| `token` | empty | Saved TV token, if you already have one |
| `slideshow_minutes` | `60` | Minutes each picture stays on screen |
