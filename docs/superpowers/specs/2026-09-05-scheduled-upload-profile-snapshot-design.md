# Scheduled Upload Profile Snapshot

## Goal

Ensure an already scheduled main video and its Short always use the channel
configuration applied to that job, regardless of later GUI profile changes.

## Root cause

The scheduling status persists only the configuration name and channel-scheme
name. Upload workers subsequently resolve the scheme against the mutable
global `config` object. Changing the GUI profile while a main upload is in
progress can therefore make its Short resolve against unrelated channel
schemes and fail with a missing-scheme error.

## Design

When a YouTube schedule is created, save a normalized copy of the selected
channel scheme in the job status as `publish_schedule_profile_snapshot`.
The main and Short upload entrypoints accept an optional profile snapshot and
select it directly after verifying its name matches the persisted scheme name.

For pre-existing scheduled jobs without a snapshot, load the job's saved
`publish_config_profile` in an isolated profile-settings read, normalize its
`browser_profiles`, and select the saved scheme name. Do not mutate the GUI's
active global configuration while resolving this fallback.

## Error handling

If a snapshot is missing or malformed and the saved configuration does not
contain the requested scheme, stop before any upload, reporting the saved
configuration and requested scheme. The existing main upload remains intact;
the Short can be retried after the configuration is repaired.

## Verification

Add regression tests showing that a snapshot selects `kiyo说` even when the
global configuration contains only unrelated Japanese schemes, and that the
legacy fallback resolves `kiyo说` from `中文kiyo说` without changing the
active global profile. Run focused tests, the complete test suite, and the
project compilation validation.

## Scope

This affects only queued YouTube main/Short upload profile resolution. It does
not change the selected channel, video metadata, timing, or publishing steps.
