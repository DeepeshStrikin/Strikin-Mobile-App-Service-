# Deploying the Strikin backend to Railway

This gives you a permanent public HTTPS URL (e.g. `https://strikin-production.up.railway.app`)
so the app works anywhere — no IP/Wi-Fi/firewall issues.

## What's already set up for you
- `Procfile` — how Railway starts the server
- `railway.json` — build + start command + `/health` healthcheck
- `.python-version` — pins Python 3.12
- `requirements.txt` — dependencies
- Secrets are read from **environment variables** (set them in Railway, NOT in the repo)

---

## Option A — Railway CLI (no GitHub needed)

1. Install the CLI (one time):
   ```powershell
   npm install -g @railway/cli
   ```
2. Log in (opens the browser):
   ```powershell
   railway login
   ```
3. From the **backend** folder, create the project and deploy:
   ```powershell
   cd "C:\Users\DeepeshPJ\Desktop\Strikin App\backend"
   railway init        # give it a name, e.g. strikin-api
   railway up          # uploads this folder and builds it
   ```
4. Add the environment variables (see the list below):
   ```powershell
   railway variables --set "DATABASE_URL=postgresql+psycopg://..." --set "RAZORPAY_KEY_ID=rzp_test_..." ...
   ```
   (or paste them in the Railway dashboard → your service → Variables)
5. Generate a public URL: Railway dashboard → your service → **Settings → Networking → Generate Domain**.

## Option B — GitHub

1. Put this project in a GitHub repo (the `.env` is git-ignored, so secrets stay private).
2. On railway.app → **New Project → Deploy from GitHub repo**.
3. In the service **Settings → Root Directory**, set it to `backend`.
4. Add the environment variables (below) under **Variables**.
5. **Settings → Networking → Generate Domain** for the public URL.

---

## Environment variables to set in Railway
Copy these from your local `backend/.env` (values not shown here for safety):

| Variable | Notes |
|---|---|
| `DATABASE_URL` | the Supabase Postgres URL |
| `RAZORPAY_KEY_ID` | `rzp_test_...` (test) |
| `RAZORPAY_KEY_SECRET` | test secret |
| `SENDGRID_API_KEY` | optional (email OTP) |
| `SENDGRID_FROM_EMAIL` | optional |
| `GMAIL_USER` / `GMAIL_APP_PASSWORD` | optional (email OTP) |
| `CORS_ORIGINS` | `*` for now, or your web app origin |
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |

---

## After it's live
1. Test it: open `https://<your-railway-url>/health` → should show `{"status":"healthy"}`.
2. Rebuild the app pointing at the new URL:
   ```powershell
   cd "C:\Users\DeepeshPJ\Desktop\Strikin App\strikin_flutter"
   flutter build apk --release --dart-define=API_URL=https://<your-railway-url>
   ```
3. Install that APK — it now works on **any** network (Wi-Fi or mobile data), and
   payment + invite + share all work over HTTPS.
