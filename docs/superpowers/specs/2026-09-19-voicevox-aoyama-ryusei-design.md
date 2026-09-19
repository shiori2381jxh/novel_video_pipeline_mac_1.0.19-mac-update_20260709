# VOICEVOX 青山龍星音色 Design

## Goal

Expose the locally installed VOICEVOX voice 青山龍星（ノーマル）in the GUI
voice picker, and make its curated display code synthesize through the correct
VOICEVOX speaker ID.

## Scope

- Add `311｜男｜青山龍星｜普通` to the curated VOICEVOX voice choices.
- Map curated code `311` to the local VOICEVOX speaker ID `13`.
- Do not modify the active settings or any profile; users opt in by selecting
  the new voice.
- Do not add other 青山龍星 styles in this change.

## Data Flow

1. The GUI displays the new curated voice option when the provider is
   `voicevox`.
2. TTS parses the leading curated code `311`.
3. The VOICEVOX backend translates it to immutable speaker ID `13` for both
   `audio_query` and `synthesis` calls.

## Error Handling

The existing behavior for direct raw speaker IDs is preserved. The curated
mapping prevents VOICEVOX from receiving the invalid raw ID `311`, which the
locally installed engine rejects with HTTP 500.

## Verification

- Add a focused automated test that verifies code `311` resolves to ID `13`.
- Run the Japanese inline-furigana tests to confirm pronunciation preparation
  remains intact.
- Run a local VOICEVOX synthesis probe using the curated value and an inline
  annotation such as `神楽（かぐら）`; confirm a valid WAV is produced and the
  narration input contains `かぐら` while subtitles retain `神楽`.
