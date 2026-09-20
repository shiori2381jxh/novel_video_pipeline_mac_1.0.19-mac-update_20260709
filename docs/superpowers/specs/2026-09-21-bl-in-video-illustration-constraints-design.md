# BL In-Video Illustration Constraints

## Goal

Ensure the `日语BL推文` profile's long-video storyboard illustrations visibly match BL source material and do not generate women or girls.

## Scope

Only edit `data/profiles/日语BL推文.json`. Do not change global defaults, other profiles, the image backend, or Short-only prompt generation.

## Design

Add the same BL constraint in the two long-video prompt layers that are sent through the normal storyboard pipeline:

1. `llm_storyboard_prompt` directs the text model to depict adult men only when people are visible, make the relationship/action consistent with male-male romance or emotional tension supported by the excerpt, and exclude women, girls, and feminine-presenting characters.
2. `llm_image_prompt_prefix` repeats the adult-men-only and no-female-characters constraint on every generated scene prompt, so the image generator receives it even if the storyboard model omits it.

The constraints do not invent romantic events absent from the source text. They only keep visible people and relationship framing aligned with the BL profile.

## Data Flow

`日语BL推文.json` supplies the storyboard system instruction and common image prefix. The pipeline combines them with the selected narration, theme, character locks, and style suffix before sending the final prompt to the image backend. No code path changes are required.

## Error Handling

Existing fallback behavior remains unchanged. The persisted profile constraints apply whenever this profile is selected, including retries and resumed jobs that use its settings snapshot.

## Verification

Add or update a focused test that loads `data/profiles/日语BL推文.json` and verifies the two long-video prompt fields contain explicit adult-male-only and no-female-character constraints. Run that test and the repository's safe Python compilation bundle.
