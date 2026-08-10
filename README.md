# HACRI-E + Deeksharambh — Integrated App

FastAPI app combining the AI Literacy Survey (HACRI-E) and Deeksharambh 2026 Orientation portal.

## Architecture

```
/ (landing)          → student enters name, email, programme
/survey/pre          → HACRI-E Baseline Assessment (65 Likert items)
/orientation         → Deeksharambh 2026 survey (if flag enabled)
/survey/post         → HACRI-E Post-Workshop Survey
/pre/<dept-slug>     → Department baseline link (registration, department locked)
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
3. `/orientation` → Deeksharambh form (identity taken from the session)
   - On submit → server stores data → redirect to `/survey/post`
4. `/survey/post` → HACRI-E Post-Workshop → submits → `/results/<slug>`
5. Results page shows 2×2 JAIN Star quadrant + histograms

### Returning through a department post link

A student opening `/post/<dept-slug>` types their email and is then **greeted by
name** — "Hey \<first name\>, welcome back!" — with their department, the date
of their baseline submission, and what is still outstanding. One button carries
them on: to the Deeksharambh orientation when they still owe it, otherwise
straight to the post survey. The orientation redirects to the post survey when
it is submitted, so the sequence is always orientation → post survey.

### Survey sections

| | Survey 1 (Baseline) | Survey 2 (Impact) |
|---|---|---|
| **A** | Your Background | Your Background (family details) |
| **B, D, E, F, G** | Scored Likert items | The same items, same wording |
| **C** | Prior AI Usage — *at school* | AI Usage — *at university* |
| **H** | Future Expectations | Post-Induction Reflection |

Section C asks the same five questions on both sides with identical answer
options; only the time frame changes ("during your school years" →
"now, as a university student"), so each answer reads directly against its
baseline counterpart. C carries no scored items — literacy and readiness come
from B, D, E, F and G alone, which is what keeps the pre/post delta valid.

### Details are asked once

Name, department and level are collected at registration and never asked again.
The orientation form (both the standalone `/orientation` wizard and the Part 1
step embedded in the post survey) shows them back as read-only pills and asks
only for the **campus — Bangalore or Kochi** — pre-selected from the
registration record when it is known.

## Admin Dashboard (`/admin`)

Two portals share one login page (`/admin/login`): the survey admin lands on
`/admin/survey`, the orientation admin on `/admin/orientation`.

### Survey admin pages (`/admin/survey`)
The department and level selectors in the top bar scope every page below them.

| Page | What it does |
|--------------|--------------|
| **Overview** | Registration / completion / reminder counts, completion split, cohort charts |
| **Students** | One table, four views — status, time taken, timeline, orientation replies — with search and status filter |
| **Emails** | Send reminders to a chosen cohort, draft a mail to open in Gmail, then track delivery, clicks and completions per department |
| **Links** | Department post-survey links, shareable analysis reports, student entry points |
| **Departments** | Literacy / readiness averages, rankings, bar chart, per-department report links |
| **Parents** | Parental occupation breakdown from the post survey |
| **Calendar** | Month grid, daily submission chart, day-by-day log (click a date for the department breakdown) |
| **Settings** | Feature toggles, post-survey delay, automatic reminder schedule |

Cohort data exports (CSV or Excel) come from the **Export** button, which
follows the current filters and lets you pick which columns to include.

### Writing a mail yourself

The **Emails** page has a composer for when you'd rather send from your own
mailbox than through the portal. Pick a department and whether to link the
baseline or the post survey, and it drafts a subject and body around that
department's link. Edit either, then:

- **Open in Gmail** — opens Gmail's compose window with the subject and body
  already filled in. Nothing sends until you press send.
- **Open in mail app** — the same via `mailto:`, for Outlook and friends.
- **Copy recipients (N)** — copies the matching students' addresses so you can
  paste them into Bcc. Short recipient lists go into the Gmail link directly;
  longer ones don't, because Gmail rejects over-long URLs, so the page tells
  you to paste instead.

### Student lookup

The search bar in the top bar finds **any** student by name, email or
department — it ignores the department/level filters, so you can reach anyone
from any page. Type two or more characters (or press **Ctrl/Cmd+K**), pick a
result with the arrow keys or the mouse, and a panel opens with everything held
about that student:

- profile, status and the full progress timeline (registered → baseline →
  orientation → post)
- email activity: reminders sent, clicks, department-link entries, send errors
  and unfinished drafts
- baseline and post scores with the change between them, quadrant and band
- every answer they gave, grouped by survey section
- shortcuts to view or re-send their results, show them in the students table,
  or delete them

Clicking a name in the students table opens the same panel.

### Overall department directory (one shareable link)

The **Links** page generates a single tokenised link —
`/shared/departments?token=…` — that opens a read-only page covering every
department at once. No admin login needed; anyone with the link can open it.

Each row shows: registered · baseline filled · post filled · post pending ·
reminders sent · clicked the mail · filled after the mail · average pre and
post scores. And each row carries its own links:

| | Opens |
|---|---|
| **Analysis** | that department's own shareable analysis page (pre and post separately) |
| **Excel** | `.xlsx` export of that department's responses |
| **PPT** | generated slide deck for that department |

The top row is **Overall (All Departments)** with the same links, so the
combined report and a full-cohort Excel are one click away. Figures are
recalculated every time the page is opened.

The Overall Excel opens on a **Department Breakdown** sheet — one line per
department (registered, baseline filled, post filled, both pendings, reminders
sent, clicked, filled after mail, average pre and post scores) closing with an
ALL DEPARTMENTS total. The second sheet holds every student, each tagged with
their department. Single-department exports carry the student sheet only.

Each department's analysis link is independently shareable — hand a single
department its own link without exposing the rest.

Every row also has an **✉️ Mail** button on each of its two lines, which opens
Gmail's compose window with the links already in the body and the top left
blank for your own message:

- **Pre** — the baseline analysis link and its Excel download link
- **Post** — the same for the post survey, plus the student survey link
  (`/post/<dept-slug>`) for that department

Nothing is sent from the page; the draft is yours to finish. Note that a Gmail
compose link cannot carry a file attachment — that is a browser limitation — so
the Excel goes in as a one-click download link. Use the row's **📥 Excel**
button first if you would rather attach the file by hand.

### Department-wise survey links

The **Links** page lists every department with two links to hand out:

| Link | Path | What the student sees |
|------|------|------------------------|
| **Outcome Survey 1 — Baseline** | `/pre/<dept-slug>` | The normal registration page with their department filled in and locked, so everyone signing up through it is filed under that department |
| **Impact — Post Survey** | `/post/<dept-slug>` | An email box — enter the address used for the baseline, and the post survey opens |

e.g. `/pre/department-of-law` and `/post/department-of-law`. `/post/all`
accepts any department; the plain `/` is the open-to-anyone baseline link.

The post link checks, in order: is the email registered, is it in **this**
department, is the baseline done, and is the post survey past its start delay.
Each failure gets a plain message on the same page instead of a redirect —
unknown email, wrong department (naming the one they *are* registered under),
baseline not done yet, or the date the survey opens. A student who already
finished both surveys is sent to their results.

Entering through a post link counts as a personal invitation, so it works even
while `post_survey_enabled` is off for everyone else (the same way a reminder
email does).

Department names live in `app/departments.py` — the registration dropdown, the
link slugs and the admin table all read from that one list, so a link always
files students under the exact official spelling. Add a department there and it
appears everywhere.

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
