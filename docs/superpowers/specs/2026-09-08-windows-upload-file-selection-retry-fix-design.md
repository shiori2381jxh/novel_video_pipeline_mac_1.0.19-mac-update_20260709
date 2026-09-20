# Windows YouTube Upload File Selection and Retry Fix

## Goal

Make Windows YouTube uploads reliably select a local video and ensure every
retry starts from a clean, dedicated Studio tab.

## Confirmed Problems

The uploader currently opens a dedicated tab, but `_do_upload` can switch to
an older Studio tab. The retry navigation and final close therefore affect the
dedicated tab while the actual upload dialog remains open in the older tab.

File selection starts by clicking the Studio button and waiting for a
Playwright file-chooser event. If the event is missed after Windows has opened
a native dialog, the subsequent hidden-input assignment is blocked. The native
fallback then clicks the button a second time without first clearing the stale
dialog.

## Design

### Dedicated Upload Tab

The page created for the current upload is the only page used by `_do_upload`.
It inherits the signed-in browser context, navigates directly to the bound
channel, and is the page reset between retries and closed at the end. Existing
Studio tabs are left untouched.

### File Selection Order

1. Use Chrome DevTools Protocol `DOM.setFileInputFiles` with the resolved local
   video path. This works with hidden file inputs, avoids a native dialog, and
   does not transfer large video bytes through Playwright.
2. If CDP assignment fails for a compatibility reason, try Playwright file
   input/chooser assignment.
3. On Windows only, close any stale native file dialogs before invoking the
   existing native picker automation as the final fallback.

Every successful method must wait for the metadata title field before the
upload flow advances.

## Error Handling

Each method logs its own failure reason. A method failure may fall through to
the next method, but the uploader returns failure if YouTube does not display
the metadata editor. A retry navigates only the dedicated upload tab back to
the bound channel page.

## Tests

Focused regression tests will verify:

- CDP local-path assignment is attempted first.
- Playwright is used when CDP assignment fails.
- Windows native fallback closes stale dialogs before it clicks the upload
  button.
- The current upload page is retained even when another Studio tab exists.

The focused tests and the validation bundle from `AGENTS.md` must pass before
the fix is reported complete.

## Scope

The change is limited to video file selection and retry tab ownership. It does
not alter channel binding, metadata, monetization, scheduling, visibility,
publishing, or retry counts.
