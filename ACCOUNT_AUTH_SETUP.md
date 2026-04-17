# Account Auth Setup

## Required Python Packages

Use the shared virtual environment at `/home/ruthe/Game/.venv`:

```bash
/home/ruthe/Game/.venv/bin/python -m pip install -r requirements.txt
```

The passkey feature specifically requires the `webauthn` package. If it is missing, the server keeps running, but account registration and login will stay disabled and `/api/me` will report `webauthn_ready: false`.

## Recommended Environment Variables

- `QUIZ_WEBAUTHN_RP_NAME`
  Default: `QuizOpenBattle`
- `QUIZ_WEBAUTHN_RP_ID`
  Example: `localhost`, `example.com`
- `QUIZ_WEBAUTHN_ORIGIN`
  Example: `http://localhost:8000`, `https://example.com`
- `QUIZ_WS_AUTH_SECRET`
  Used for signed WebSocket tickets
- `QUIZ_SESSION_MAX_AGE_SECONDS`
  Optional long-lived session TTL. Default is 180 days.

## Local Verification Checklist

1. Start the app with the dependencies installed.
   Example:
   `/home/ruthe/Game/.venv/bin/uvicorn backend.server:app --reload --host 0.0.0.0 --port 8000`
2. Open the login screen and confirm the passkey buttons are enabled.
3. Create an account with a passkey.
4. Reload the page and confirm `/api/me` keeps the session alive.
5. Log in again with the same passkey.
6. Join the game and verify WebSocket connection still rejects duplicate tabs.
7. Open the kifu list and confirm old matches linked through the existing `client_id` are visible.
8. Finish a match and confirm the profile stats increase after the result is broadcast.

## Notes

- Existing gameplay state is still keyed by `client_id` internally for compatibility.
- Account identity is now based on `user_id + session_id`.
- Legacy kifu access is preserved by linking the browser's existing `client_id` to the new account during registration or login.
- This repository is expected to use the shared venv at `/home/ruthe/Game/.venv` rather than a local `QuizOpenBattle/.venv`.
