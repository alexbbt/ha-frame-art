# Frame Art to-do

## Done

- Folders live in this app. The TV only has My Photos and Favorites.
- Play a folder to rotate that set. Play every photo to rotate the whole pile.
- Remove deletes a picture from the TV.
- A batch of photos is sent one at a time. One failure does not drop the rest.
- The page is served from the Home Assistant host. This repo has no house-specific addresses.

## Next

- Show the pictures that are already on the TV. The Frame can return a thumbnail for each artwork (`get_thumbnail_list`). The page should show those images, not only file names, for photos in a folder and for anything sitting in My Photos.
- Put the TV's own art settings on this page, using the same controls Home Assistant already has. Do not invent a separate timer.
  - How long each picture stays up, and shuffle or in order. This is the TV slideshow setting.
  - Art brightness.
  - Color temperature.
  - Motion sensitivity.
  - Brightness sensor.
  - How long Art Mode stays on before the panel sleeps (`off`, 5, 15, 30, 60, 120, 240 minutes).
- After a folder is playing, changing the slideshow duration should update that same TV setting.
