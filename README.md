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

### Signing in takes two steps

The password alone opens nothing. Get it right and a six-digit code goes to the
portal's registered mailbox (`SURVEY_ADMIN_OTP_EMAIL` /
`ORIENTATION_ADMIN_OTP_EMAIL`); that code finishes the sign-in. Whoever ends up
with the password still needs the mailbox.

- The code is valid for ten minutes and is spent the moment it is used.
- **Send it again** only works for a browser that already passed the password —
  a code cannot be requested with a username alone, because that would be a
  login of its own.
- Both halves land in the sign-in log: *Code sent*, then *Signed in*.

`ADMIN_REQUIRE_OTP=false` in the `.env` falls back to password-only sign-in.
That is the way back in when mail is down, and nothing else — with it off, a
stolen password is the whole login again. The log says plainly when a sign-in
skipped the code.

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
| **Security** | Who has signed in and who has tried, grouped by address, with a **Block** button per address |
| **Settings** | Feature toggles, post-survey delay, automatic reminder schedule |

Cohort data exports (CSV or Excel) come from the **Export** button, which
follows the current filters and lets you pick which columns to include.

### Turning an address away

Six failures from one address inside fifteen minutes blocks it automatically for
fifteen minutes — right for someone fumbling their own password, useless against
a scanner that comes back all day. The **Security** page adds the manual version:

- **Block** on any row in *Addresses that failed*, or type an address into the
  box under *Blocked by hand* with an optional reason.
- Choose 1 hour, 24 hours, 7 days, or until you lift it. A timed block clears
  itself; the rest stay until **Unblock**.
- A blocked address is refused at the password step, before the credentials are
  read, so the right password gets it nowhere.
- You cannot block the address you are sitting on — that would lock you out of
  your own next sign-in.

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

### Deeksharambh report links (campus, and one per department)

The **Orientation** page hands out read-only links to the same orientation
report the admin reads. They need no login, show aggregate figures only, and
name no student.

| Where | Link | Opens |
|---|---|---|
| Orientation page | `/shared/orientation?campus=…&token=…` | that campus's full analysis, with a department picker |
| Orientation → **Departments** | `/shared/orientation?campus=…&dept=…&token=…` | one department's own report, and nothing else |

Both wear the same look: a near-white ground, white cards with hairline
borders, small uppercase micro-labels over large tight-set numerals, and one
warm coral accent on the chrome. Colour is spent only where it means
something — the mood ramp (green through amber to coral) on vibe figures, and
the status pill on each department row, which tints itself from the mood it is
printing.

A department link is signed for that department alone: the token is minted from
campus **and** department, so editing `dept=` in the URL closes the page rather
than opening the neighbouring department. The department picker becomes a
label, the leaderboard naming every other department is replaced by that
department's **vibe scorecard** — its rank on vibe, its reply and pending
counts, and vibe / recommendation / belonging / will-succeed / bridge-course
each marked against the campus average — and the slide deck downloads scoped
the same way.

The **Departments** tab lists every department with its counts and vibe next to
its link, with a filter box, so the right one is quick to find and obviously
worth sending (or not, when only two students have answered). **Copy share
link** at the top of the report follows what is on screen: the department when
the top-bar department filter is set, the campus otherwise.

Campus links handed out earlier keep working unchanged.

### The Deeksharambh deck

Every orientation report — the admin's, the campus share link's, a department
share link's — downloads as the same `.pptx`, built to the house design of the
printed *Student Experience Analysis Report*: a mint ground with a white panel
on it, navy serif headings centred and underlined, a section kicker above each
one, teal meters for the averages, and a department-wise chart with the
observations listed beside it.

| Slide | What it carries |
|---|---|
| Cover | Title, scope, response count, and the overall vibe with its mood word |
| Response overview | Total responses, the campus split with UG/PG, and the departments answering most and least |
| Department wise — who has answered | Filled against still-pending, per department |
| Section I — Program effectiveness | Vibe, belonging, confidence and recommendation as meters, with the answer most students actually chose |
| Section I — department wise | Vibe, belonging and confidence, department by department |
| Section II — Academic foundation | Bridge Course confidence, readiness for classes, and the areas that helped |
| Section II — department wise | Bridge Course confidence, department by department |
| Section III — Engagement and networking | The three sessions with the biggest impact, and the recommendation picture |
| Section III — department wise | Promoters against detractors, as a share of that department's own answers |
| What to keep, what to fix | The loudest answers on both sides |
| Score by score | The 1–10 distribution and the NPS ring |
| Section IV — Aspirations and growth | Most helpful aspects, top expectations, and the closing figures |
| Department scoreboard | Every department's numbers in one table |
| In one line | The sentence to quote |

The observations beside each chart are composed from the same figures the
charts draw — the highest and lowest department, the cohort average, who
answered most — and never from anything else. Where the deck reports a
single-choice question it quotes the answer students actually gave ("Yes,
mostly (64%)") rather than bucketing wordings into a yes.

### Mailing a report

Every directory row has an **✉️ Mail** button on each of its two lines, and each
department's analysis page has **✉️ Mail this report**. Both open a compose
dialog that asks for the subject and your message first, then adds that
department's links below it:

- **Pre** — baseline analysis, Excel, PPT
- **Post** — the same for the post survey, plus the student survey link
  (`/post/<dept-slug>`) for that department

Two formats:

| | What you get | How it goes out |
|---|---|---|
| **📄 Normal mail** | Plain text with the URLs listed | **Open in Gmail** fills the compose window directly; **Mail app** does the same via `mailto:` |
| **🎨 HTML mail** | A quiet, letter-like page — JAIN logo on white, the department as the heading, your message, then each link named with its full URL printed in view | **Copy styled mail**, then paste into the compose window (Ctrl+V). **Preview** opens it in a tab first |

Addresses typed into **To** are carried into the compose window and recorded.

Both formats carry that department's **figures** in the body — registered,
baseline filled, post filled, post pending, and the average AI literacy and
readiness for whichever survey the mail is about. The reader sees the numbers
without having to open a link.

HTML has to be pasted because a compose link can only carry plain text — the
copy puts both a rich and a plain flavour on the clipboard, so pasting into
Gmail keeps the layout and buttons.

Whatever you write is remembered. Open the dialog for the next department and it
offers **"You wrote a message for &lt;dept&gt;. Use the same wording here?"** —
accepting keeps your text and retargets the subject to the new department.

Nothing is sent from the page; the draft is always yours to finish. A mail link
cannot carry a file attachment either, so the Excel goes in as a one-click
download — download it first if you would rather attach the file by hand.

**Mail history.** Each department's analysis page ends with a panel listing
every draft opened from that report: who it was addressed to, how many times
each person has been mailed, and when they were last mailed. Records are kept
per department (`mail_exports`) and written when the draft is handed to Gmail,
the mail app, or the clipboard. It records what was *drafted*, not what was
delivered — the sending happens in your own mailbox, which the portal cannot
see.

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

#### How long after the baseline the post survey opens

Every row on the **Links** page has a **Post opens after** box: the number of
days after a student finishes their baseline before their post survey unlocks.
Leave it empty and the department follows the portal-wide delay set on the
**Settings** page; type a number (0–365) and that department uses its own —
`0` opens the post survey the moment the baseline is submitted.

The number applies wherever the post survey is gated: the department post link,
the `/survey/post` page and the submit endpoint all read it, so a student who
arrives early is told the date theirs opens rather than let in. The shared
department directory and the analysis report both state the wait next to the
post link, and a mail drafted from either carries it in the link's description
— so nobody hands out a link expecting it to open straight away.

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
