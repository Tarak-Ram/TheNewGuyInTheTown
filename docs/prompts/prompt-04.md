<!-- Prompt 4: web voice call -->

Implement C-1, C-2, C-3, C-5 and C-7 using browser audio, not telecom.
Create a voice-gateway service with a WebSocket endpoint that connects to the Gemini Live API from the server.
Use GEMINI_LIVE_MODEL. Send 16-bit PCM 16 kHz input, and play 24 kHz output in the browser.
Use the PG Caller instruction from the PRD. Add record_fact, mark_opt_out and end_call as tools.
Enable input and output transcription with te-IN, hi-IN and en-IN hints.
Handle interruptions, goAway and session resumption.
The demo owner page must say clearly that this is a demo owner.
Test opt-out, approval and a simulated disconnect.
