# Putting the dashboard online — no terminal, updates itself

The result: a web address you can open on your phone or laptop, showing a
reading that refreshes on its own every weekday evening.

Two free services do the work, both operated from your browser:

- **GitHub Pages** serves the page
- **GitHub Actions** runs the data fetch on a timer

Total setup: about 20 minutes of clicking. No installs. No commands.

---

## Before you start

Your dashboard will be **publicly visible** to anyone who has the link. Free
GitHub Pages requires a public project. Nothing personal is published — only
market data and code — but the link is not private. If that matters, keep
running it on your own machine instead.

---

## Step 1 — Make a GitHub account

Go to **github.com** and click **Sign up**. Free plan. Verify your email.

## Step 2 — Create the project

1. Click the **+** at the top right → **New repository**
2. Repository name: `volume-regime`
3. Choose **Public**
4. Tick **Add a README file**
5. Click **Create repository**

## Step 3 — Upload the files

1. Click **Add file** → **Upload files**
2. Drag in these eight files:
   - `regime.html`
   - `regime_engine.py`
   - `fetch_regime.py`
   - `make_demo.py`
   - `demo_data.json`
   - `requirements.txt`
   - `test_engine.py`
   - `crosscheck.js`
3. Scroll down, click **Commit changes**

Do **not** upload `workflow_update.yml` this way — it needs a specific
location, which is the next step.

## Step 4 — Add the scheduled job

This is the only fiddly step. Read it twice.

1. Click **Add file** → **Create new file**
2. In the filename box at the top, type exactly:

   ```
   .github/workflows/update.yml
   ```

   As you type each `/`, GitHub turns it into a folder. That's correct.

3. Open `workflow_update.yml` from your downloads in Notepad (or TextEdit),
   select all, copy, and paste it into the big editing box.
4. Click **Commit changes**, then **Commit changes** again in the popup.

> If TextEdit on Mac shows formatting, use **Format → Make Plain Text** first.

## Step 5 — Let the job save its results

1. Click **Settings** (top of your repository)
2. Left sidebar → **Actions** → **General**
3. Scroll to **Workflow permissions**
4. Select **Read and write permissions**
5. Click **Save**

Skipping this makes the job fail at the last step every time.

## Step 6 — Run it once by hand

1. Click the **Actions** tab
2. If asked to enable workflows, click the green button
3. Left sidebar → **Update volume regime**
4. Right side → **Run workflow** → green **Run workflow** button

A yellow dot appears, meaning it's running. It takes 3–6 minutes.

- **Green tick** — it worked. Continue.
- **Red cross** — click into it and read the failed step. See troubleshooting below.

## Step 7 — Turn on the website

1. **Settings** → left sidebar → **Pages**
2. Under **Source**, choose **Deploy from a branch**
3. Branch: **main**, folder: **/ (root)**
4. Click **Save**

Wait 2–3 minutes, then refresh the page. A link appears at the top:

```
https://YOUR-USERNAME.github.io/volume-regime/regime.html
```

That's your dashboard. Bookmark it. Add it to your phone's home screen.

---

## What happens now

Every weekday around 17:30 IST the job wakes up, fetches the day's data,
checks it looks sane, and updates the page. You do nothing.

GitHub runs free scheduled jobs on a best-effort basis, so it may fire
anywhere from on time to an hour late. It is not broken.

To force an update, use **Actions → Update volume regime → Run workflow**.

If the update ever stops silently, the dashboard tells you: a warning bar
appears once the reading is four or more days old.

---

## Two things that will eventually go wrong

**GitHub pauses schedules on quiet projects.** After 60 days with no activity
from you, scheduled jobs are switched off and GitHub emails you about it. Click
the link in that email, or visit the Actions tab and re-enable. Opening the
repository occasionally is enough to avoid it.

**The data source may block cloud servers.** Yahoo Finance sometimes refuses
requests from datacentre addresses like GitHub's. The job retries three times
before giving up, and refuses to publish a half-built file — so a bad day
leaves yesterday's reading in place rather than breaking the page. If it fails
for several days running, that's the cause, and running the fetch on your own
machine remains the reliable fallback.

---

## Troubleshooting

| Red cross on the step | What it means |
|---|---|
| **Install dependencies** | `requirements.txt` didn't upload, or the name is misspelt |
| **Fetch market data** | Data source refused or rate-limited. Try again in an hour |
| **Check the file looks sane** | Too few stocks came back. The guard did its job — nothing was published |
| **Publish the updated data** | Step 5 was missed. Set write permissions and re-run |

**Page shows "Showing demo data"** — the fetch has never succeeded. Check
Actions for a green tick, and confirm `regime_data.json` now appears in your
file list.

**Link gives a 404** — give Pages five minutes after Step 7. Check the address
ends in `/regime.html`.

**Changed a setting and want it live** — edit the universe or years in
`.github/workflows/update.yml` (click the pencil icon), commit, then run the
workflow manually.

---

## Changing what it tracks

In `.github/workflows/update.yml`, find this line:

```
if python fetch_regime.py --universe nifty500 --years 3; then
```

You can change `nifty500` to `nifty200`, `nifty50` or `midsmall`, and `--years`
to a longer history. Stick with `nifty500` unless you have a reason — a small
universe makes the ratio jump between bands on very little news, which is the
main way this reading misleads people.

To run at a different time, change the cron line. It is written in UTC:
IST is UTC + 5:30, so `0 12` means 17:30 IST.
