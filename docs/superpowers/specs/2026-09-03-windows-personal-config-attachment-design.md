# Windows Personal Configuration Attachment Design

## Goal

Include `personal_config_windows_20260903` in Windows release archives as a
manual-import attachment, without changing the fresh-install configuration.

## Scope

- The folder is included only in packages built with `--platform windows`.
- Its current directory structure and files are copied unchanged.
- The release root `data/` continues to be created solely by
  `copy_sanitized_data()`, retaining its existing API-key scrubbing behavior.
- macOS packages do not include the folder.

## Architecture

`scripts/build_release_package.py` will define the attachment directory as a
Windows-only release input. During `copy_source()`, it will recursively copy
that directory into the staging root, using the same ignore rules that apply
to other copied directories. The attachment retains its own
`Import_My_Config_Windows.bat` and PowerShell script, so importing remains an
explicit operator action after extraction.

## Data Flow

1. The package builder creates the staging folder and copies normal program
   files.
2. For Windows only, it copies `personal_config_windows_20260903/` into the
   staging folder.
3. It writes the normal sanitized `data/settings.json` and default profile.
4. The archive contains both the clean default `data/` directory and the
   separate manual-import attachment.

## Error Handling

If the attachment directory is absent, the builder should fail with a clear
error for Windows builds rather than silently produce a package missing the
requested configuration. macOS builds must not require the folder.

## Verification

- Build a Windows archive into a temporary output directory.
- Inspect the ZIP file list to confirm the attachment, its import scripts,
  profiles, dictionaries, settings, and YouTube channel bindings are present.
- Confirm the regular release `data/settings.json` remains the sanitized
  fresh-install configuration rather than the attachment's settings file.
- Run the repository's required Python compile checks for the package script.
