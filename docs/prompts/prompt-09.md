<!-- Prompt 9: real phone calls, only after the compliance gate -->

Implement C-6 behind CALLING_ENABLED=false using the Exotel Connect Voice AI API and bidirectional stream.
Verify the current Exotel docs. Handle start, media and stop events, status callbacks, retries and idempotency.
Before every call, verify consent, mover approval, opt-out status, calling hours and call limits in code.
Convert audio correctly between Exotel and Gemini, and measure latency.
Test only with numbers in an allowlist. Do not enable production calling.
