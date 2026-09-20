# Upload Cancellation Design

## Goal

After the operator presses Stop, the current YouTube upload must not launch, relaunch, or reconnect Chrome for that upload attempt.

## Scope

Keep the signed-in Chrome instance intact. The change only cancels the pipeline's future browser actions; it does not forcibly close Chrome or retract a file that YouTube has already received.

## Design

Pass the existing upload job cancellation token into the Chrome lifecycle helpers. Those helpers check cancellation before spawning Chrome and during their port-ready waits. Replace retry/restart waits in the upload loop with a cancellation-aware wait. Each retry branch checks cancellation before logging or starting a new browser action.

## Error Handling

Cancellation returns from the upload path normally and writes the existing "上传已取消" log entry. A cancellation during a wait exits promptly without treating it as a Chrome error or scheduling another retry.

## Testing

Add focused unit tests for the cancellation-aware wait and Chrome launch guard, using a cancelled job token and monkeypatched sleep/process primitives. Verify that a cancelled upload does not call `subprocess.Popen` and that interrupted retry waits report cancellation.
