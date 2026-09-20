# Windows YouTube Upload File Selection

## Goal

Make the Windows browser-upload flow reliably move beyond YouTube Studio's
"Select files" page when scheduling an already-rendered local video.

## Root cause

The current Windows-only path clicks YouTube's Select files button and waits
for a native `#32770` file picker. In the affected run the picker did not
become visible, so no local MP4 was supplied. The retry then remained in the
upload dialog, where the next attempt could no longer find Studio's Create
button.

## Design

`_select_file_via_dialog` will prefer browser-native file-input assignment on
Windows as well as macOS/Linux:

1. Use Playwright's file chooser and set the resolved video path.
2. If the CDP-attached browser rejects a large transfer, use Chrome CDP's
   `DOM.setFileInputFiles` with the local path.
3. Only if those methods fail for a compatibility reason, fall back to the
   existing native Windows picker automation.

Each failure path will log the method attempted and its reason. Successful
assignment must still wait for the metadata title field, so the uploader only
advances after YouTube accepts the file.

## Error handling

If all three paths fail, the upload run returns a clear file-selection error
and the existing retry mechanism can restart from Studio. No publishing or
scheduling action occurs until file acceptance is confirmed.

## Verification

Add focused tests for the selection order and fallback behavior, including a
case where Playwright reports its remote large-file limitation. Run those
tests, Python compilation, and the project's safe validation bundle.

## Scope

This changes only file selection before upload. It does not change channel
binding, title/description entry, YouTube scheduling, or retry counts.
