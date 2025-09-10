# Promptfoo eval for Lighthouse Analyst

This Promptfoo setup logs in to the local Next.js app, calls the Lighthouse Analyst endpoint, aggregates streamed output to final text, and asserts expected content.

## Quick start

1) Install Promptfoo

```bash
# Recommended (always latest)
npx promptfoo@latest --help

# Or install globally
npm install -g promptfoo@latest
```

2) Create env file: `promptfoo/.env`

```bash
NEXTJS_BASE_URL=http://localhost:3000
NEXTJS_EMAIL=your_user@example.com
NEXTJS_PASSWORD=your_password_here
```

3) Run the eval from repo root

```bash
promptfoo eval -c ./promptfoo/promptfooconfig.yaml --env-path ./promptfoo/.env --no-cache
```

Results will be written to `./promptfoo/results.json`.

## How it works

- Login uses the Next.js server action at `/sign-in` that requires a dynamic `Next-Action` hash (40 hex). The extension discovers this hash from the sign-in page chunks.
- Login request format:
  - Header: `Next-Action: <hash>`
  - Body: `[null, { "email": "...", "password": "..." }]`
- On success, only the session cookie is used: `authjs.session-token=...`.
- This cookie must be sent on every protected request, e.g. `POST /api/lighthouse/analyst`.
- Promptfoo headers interpolate environment variables; the config sends `Cookie: {{env.AUTH_COOKIES}}`.
- The single extension (`extensions/session.js`) performs login, extracts the session cookie, and sets `process.env.AUTH_COOKIES`; the provider config reads it to send the Cookie header.
- The Analyst route streams tokens; `transformResponse` aggregates the stream to a final string used for assertions.

## Files

- `promptfooconfig.yaml` – HTTP provider config, headers, prompts, test, stream parser
- `extensions/session.js` – Single extension: login + session cookie injection
- `results.json` – Last evaluation output (generated)

## Troubleshooting

- 500 with `business_context` undefined: authentication failed or Lighthouse config missing. Verify credentials and that `Cookie` header is present.
- If the `Next-Action` hash isn’t found, ensure the app is running at `NEXTJS_BASE_URL` and the sign-in page/chunks are accessible.
- Update the test assertion text in `promptfooconfig.yaml` under `tests.assert` as needed.
