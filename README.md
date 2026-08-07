# HACRI-E + Deeksharambh — Integrated App

FastAPI app combining the AI Literacy Survey (HACRI-E) and Deeksharambh 2026 Orientation portal.

## Architecture

```
/ (landing)          → student enters name, email, programme
/survey/pre          → HACRI-E Baseline Assessment (65 Likert items)
/orientation         → Deeksharambh 2026 survey (if flag enabled)
/survey/post         → HACRI-E Post-Workshop Survey
/post/<dept-slug>    → Department post-survey link (email → post survey)
/results/<slug>      → Personal results + JAIN Star charts
/admin               → Admin dashboard
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

Two portals share one login page (`/admin/login`): the survey admin lands on
`/admin/survey`, the orientation admin on `/admin/orientation`.

### Survey admin pages (`/admin/survey`)
The department and level selectors in the top bar scope every page below them.

| Page | What it does |
|--------------|--------------|
| **Overview** | Registration / completion / reminder counts, completion split, cohort charts |
| **Students** | One table, four views — status, time taken, timeline, orientation replies — with search and status filter |
| **Emails** | Send reminders to a chosen cohort, then track delivery, clicks and completions per department |
| **Links** | Department post-survey links, shareable analysis reports, student entry points |
| **Departments** | Literacy / readiness averages, rankings, bar chart, per-department report links |
| **Parents** | Parental occupation breakdown from the post survey |
| **Calendar** | Month grid, daily submission chart, day-by-day log (click a date for the department breakdown) |
| **Settings** | Feature toggles, post-survey delay, automatic reminder schedule |

Cohort data exports (CSV or Excel) come from the **Export** button, which
follows the current filters and lets you pick which columns to include.

### Department-wise post-survey links

The **Links** page generates one link per department, e.g.
`/post/department-of-law` (plus `/post/all` for any department).

1. Share the link with that department's students.
2. A student opens it and enters the email they registered with.
3. If that email has a **completed baseline survey in that department**, the
   post survey opens immediately — no landing page, no re-registration.
4. Otherwise the page says why: unknown email, wrong department, baseline not
   done yet, or post survey still time-locked. A student who already finished
   both surveys is sent to their results.

Entering through a department link counts as a personal invitation, so it works
even while `post_survey_enabled` is off for everyone else (the same way a
reminder email does).

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
