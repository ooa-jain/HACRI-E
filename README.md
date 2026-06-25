# HACRI-E + Deeksharambh — Integrated App

FastAPI app combining the AI Literacy Survey (HACRI-E) and Deeksharambh 2026 Orientation portal.

## Architecture

```
/ (landing)          → student enters name, email, programme
/survey/pre          → HACRI-E Baseline Assessment (65 Likert items)
/orientation         → Deeksharambh 2026 survey (if flag enabled)
/survey/post         → HACRI-E Post-Workshop Survey
/results/<slug>      → Personal results + JAIN Star charts
/admin               → Admin dashboard (tabbed)
```

## MongoDB Collections

| Collection             | Contents                                  |
|------------------------|-------------------------------------------|
| `users`                | All registered students + status flags    |
| `pre_responses`        | HACRI-E baseline submissions              |
| `post_responses`       | HACRI-E post-workshop submissions         |
| `orientation_responses`| Deeksharambh survey submissions           |
| `feature_flags`        | `survey_enabled`, `orientation_enabled`   |

## Student Flow

1. Student visits `/` → enters **name, email, programme** → lands at `/survey/pre`
2. Fills HACRI-E Baseline → submits
   - If **orientation flag ON** → redirected to `/orientation`
   - If **orientation flag OFF** → `/survey/pre/done` → manual link to `/survey/post`
3. `/orientation` → Deeksharambh form (email pre-filled from session)
   - On submit → server stores data → redirect to `/survey/post`
4. `/survey/post` → HACRI-E Post-Workshop → submits → `/results/<slug>`
5. Results page shows 2×2 JAIN Star quadrant + histograms

## Admin Dashboard (`/admin`)

### Tabs
- **Overview** — counts: registered / pre done / post done / orientation done + feature status
- **Settings** — toggle `AI Survey` and `Orientation` on/off in real-time
- **AI Survey** — table of all users with status, programme, timestamps; search by name/email/programme
- **Orientation** — table of Deeksharambh submissions; search by name/email
- **Alerts** — one-click "Send Reminder" to all pre_done (post-pending) students

### Feature Flags
| Flag                | Effect when OFF                                         |
|---------------------|---------------------------------------------------------|
| `survey_enabled`    | `/survey/pre` redirects to `/locked`; landing shows closed message |
| `orientation_enabled`| `/orientation` returns 404-like disabled page           |

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in values
uvicorn app.main:app --reload   # dev
gunicorn app.main:app -c gunicorn.conf.py   # prod
```

## Deploy on VPS

```bash
# Copy to server
scp -r . root@31.97.186.191:/var/www/hacri_e2_integrated/

# On server
cd /var/www/hacri_e2_integrated
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp hacri_e2_integrated.service /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now hacri_e2_integrated
# Nginx
cp nginx.conf.example /etc/nginx/sites-available/ai-survey.juooa.cloud
ln -s /etc/nginx/sites-available/ai-survey.juooa.cloud /etc/nginx/sites-enabled/
certbot --nginx -d ai-survey.juooa.cloud
nginx -t && systemctl reload nginx
```

## Admin Credentials
Set `ADMIN_USERNAME` and `ADMIN_PASSWORD` in `.env`.  
Default: `admin` / `adminjain2026`

## Email Alerts
Set `EMAIL_DRY_RUN=false` and fill SMTP vars in `.env` for real emails.
