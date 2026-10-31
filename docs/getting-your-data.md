# Getting your data

You need one export from each service you use. **Send both requests today**: Netflix and Amazon each email you a
.zip, usually within a day or two but sometimes longer. Leave the files in your **Downloads** folder as they are (no
unzipping, no opening in Excel), then double-click `run.cmd`, or run `python scripts/run_pipeline.py --import`.

| | How | Time | File you end up with |
|---|---|---|---|
| Netflix | Ask Netflix for a copy of your personal information | hours to days, by email | `netflix-report.zip` (any name is fine) |
| Amazon Prime Video | Ask Amazon for your Prime Video data | days, by email | `Prime Video.zip` |
| Amazon, same day | Or: run a small open-source script on your watch history page | ~5 minutes | `watch-history-export-<date>.csv` |
| TMDB key | Free sign-up | ~5 minutes, one time | a key you paste when the pipeline asks |

## Netflix

1. Sign in on a computer at **[netflix.com/account/getmyinfo](https://www.netflix.com/account/getmyinfo)**, using the
   account owner's email and password. (Same page from the menus: your profile icon → **Account** →
   **Security & privacy** / **Privacy** → **Download your personal information**. Netflix renames these menus now
   and then; the link above is the stable way in.)
2. Click **Submit request**.
3. Open the confirmation email from Netflix and click **Confirm**. Nothing happens until you do.
4. Wait for the second email saying your information is ready. Netflix allows up to 30 days, but it usually arrives
   much sooner.
5. Click the link in that email and **Download** the .zip. Do this soon: the download link expires.
6. Leave the .zip in Downloads as is. There is no need to unzip it. The pipeline reads `ViewingActivity.csv` and
   `Ratings.csv` from inside it and ignores everything else.

One request covers **every profile** on the account. When the pipeline runs, it lists the profiles with their view
counts. To leave some out (the kids', a guest's), put the names to keep in `data/staging/profiles.txt`, one per line.

> The **Download all** link at the bottom of a profile's *Viewing activity* page gives a different, smaller file
> (`NetflixViewingHistory.csv`: title and date only, one profile, no ratings or minutes watched). The pipeline
> doesn't read that file. Use the full request above.

## Amazon Prime Video

Two ways, and either one is enough:

| | Amazon's data request (recommended) | Exporter script |
|---|---|---|
| Effort | a few clicks, then wait for email | paste a script into the browser console |
| Arrives | days (Amazon allows up to a month) | in about 5 minutes |
| Your Likes / Dislikes | yes | no |
| Minutes watched | yes, so 5-minute samples are left out | no |
| Movie or TV | not stated; worked out from the title and checked on TMDB | stated by Amazon |

### Amazon's data request

1. Sign in at **[Amazon → Request your data](https://www.amazon.com/hz/privacy-central/data-requests/preview.html)**.
2. Click **Prime Video**, then **Submit request**.
3. Click the confirmation link Amazon emails you. Nothing happens until you do.
4. Wait for the "your data is ready" email, open the link, and download the file. It is called
   `Prime Video.zip`. Leave it zipped in Downloads.

The pipeline reads `Viewing History.csv` (every playback) and `Customer Feedback.csv` (your Likes and Dislikes)
from inside the zip. The other files (IP addresses, search history and so on) are never read.

### Exporter script (same day)

[Watch History Exporter for Amazon Prime Video](https://github.com/twocaretcat/watch-history-exporter-for-amazon-prime-video)
is a small open-source script that reads your watch history page and saves it as a CSV. It runs in your own
browser, signed in as you, and sends nothing anywhere else. Use it if you want your graph today.

1. In Chrome or Edge, open **[primevideo.com/settings/watch-history](https://www.primevideo.com/settings/watch-history)**
   and sign in. If several people share the Amazon account, it is the account's watch history either way.
2. **Reload the page and don't scroll.** Scrolling first can make the script miss titles.
3. Open the script's file: the `watch-history-exporter-for-amazon-prime-video.js` file in
   [that repository](https://github.com/twocaretcat/watch-history-exporter-for-amazon-prime-video). Click it, then
   use the **Copy raw file** button (two overlapping squares, top right of the code), or click in the code and
   press **Ctrl+A**, **Ctrl+C**.
4. Back on the Prime Video tab, press **F12** (or **Ctrl+Shift+J**; on a Mac **Cmd+Option+J**) and click the
   **Console** tab.
5. Click in the console, press **Ctrl+V**, then **Enter**.
   - If Chrome warns about pasting, type `allow pasting`, press Enter, and paste again.
   - `Uncaught SyntaxError: Unexpected identifier` means only part of the file was copied. Copy it again with Ctrl+A.
6. The script scrolls through your history by itself. When it finishes, it saves
   `watch-history-export-<date>.csv` to Downloads. If no file appears, allow **Pop-ups and redirects** and
   **Automatic downloads** for primevideo.com (click the icon at the left end of the address bar) and run it again.
7. Close the console (F12).

You are pasting someone else's code into a page where you are signed in, so it is reasonable to look it over first.
It is short and readable, or you can ask Claude to read it for you.

## TMDB API key (once)

1. Create a free account at [themoviedb.org/signup](https://www.themoviedb.org/signup) and confirm the email.
2. Go to [themoviedb.org/settings/api](https://www.themoviedb.org/settings/api) → **Create** → **Developer**,
   accept the terms, and fill in the form. "Personal project", any URL (your GitHub repo works), and a one-line
   description are fine.
3. Copy the **API Key** (the short one, not the long "API Read Access Token").
4. The first time you run the pipeline, paste it when asked and answer **Y** to save it. You won't be asked again.

## Later updates

Request again (or rerun the Amazon script) whenever you want a fresh graph. Each export holds your whole
history, so the newest one replaces the old one. `--import` handles that, and only new titles are looked up on TMDB.
