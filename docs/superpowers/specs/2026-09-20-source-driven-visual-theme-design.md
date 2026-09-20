# Source-Driven Visual Theme Design

## Goal

Generate in-video illustrations from the novel's stated genre, era, locations, and world rules. No default, saved profile, template, or fallback prompt may force Japanese isekai/light-novel/fantasy imagery.

## Scope

- Replace isekai-specific wording in the saved settings, all bundled templates, and every saved production profile with neutral source-driven wording.
- Update character analysis so its visual theme and recurring background are inferred from the imported text, not a preset genre.
- Update storyboard, character-reference, and cover-related visual wording that can bias normal image generation toward isekai.
- Replace the storyboard fallback's hard-coded isekai style with a source-grounded fallback.
- Preserve only general anime/editorial rendering quality where applicable; it must not imply a fantasy setting, medieval era, magic, castles, or dungeon imagery.

## Data Flow

1. Character analysis reads the source text and returns a visual theme appropriate to its content.
2. Scene generation appends that derived theme and the scene-specific narration to each image prompt.
3. If analysis or storyboard generation is unavailable, the fallback tells the image model to depict only the source text's stated world, era, locations, characters, and events.

## Acceptance Criteria

- Repository defaults, templates, saved settings, and saved profiles contain no `isekai`, `异世界`, or forced fantasy-world wording in image-generation fields.
- The storyboard fallback does not contain `isekai` and explicitly follows the source's world and era.
- A regression test proves the fallback is source-driven and does not reintroduce the removed style lock.
- Existing prompt assembly continues to add scene text, optional character locks, and analysis-derived theme context.

## Non-goals

- Do not add genre-selection UI or a manually chosen visual preset.
- Do not change API routing, image provider behavior, or image dimensions.
