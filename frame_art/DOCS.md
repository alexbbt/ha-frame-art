# Frame Art

## About

Web page for putting your own pictures on a Samsung Frame. Files land in an inbox folder. A Home Assistant automation sends that folder to the TV.

```
phone or computer  -->  this page  -->  inbox folder  -->  Frame Art Mode
```

This is a Home Assistant app (formerly an add-on) for Home Assistant OS or Supervised.

## Page

Open **Open Web UI**, or port **8391** on the Home Assistant machine.

The page accepts JPEG, PNG, WebP, and HEIC. HEIC is converted to JPEG before it is saved. Pictures larger than 40 MB are refused.

## Configuration

| Option | Default | Description |
|--------|---------|-------------|
| `inbox` | `/homeassistant/www/frame-art/inbox` | Where new pictures are written |
| `uploaded` | `/homeassistant/www/frame-art/uploaded` | Folder shown as already sent, once something else moves files there |
