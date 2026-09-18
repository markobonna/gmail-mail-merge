# gmail-mail-merge

**A mail merge that runs on your laptop and sends as you — no SaaS, no add-on, no access to your inbox.**

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/downloads/)

One Python file. It reads a CSV, personalizes a plain-text template, and sends each message through the Gmail API as your own account.

```
recipients.csv  ─┐
                 ├─→  merge.py  ─→  Gmail API (scope: gmail.send)  ─→  your recipients
template.txt    ─┘                       │
                                         └─→  sent_log.csv  (resume-safe)
```

### Why this exists

Most mail-merge tools are browser add-ons that want read access to your entire mailbox, your Drive, and your contacts, and they route your relationships through someone else's servers. This one asks for a single OAuth scope — `gmail.send` — which cannot read a single email in your inbox. Your list, your template, and your OAuth token never leave your machine.

### Safety by design

| | |
|---|---|
| **Dry-run is the default** | `python merge.py` prints what it *would* send. Nothing leaves until you add `--send`. |
| **One scope: `gmail.send`** | No inbox read, no Drive, no Sheets, no contacts. |
| **Resume-safe** | Every send is appended to `sent_log.csv`; re-running skips anyone already sent. Safe to interrupt with Ctrl-C. |
| **Throttled** | 2 seconds between sends by default. |
| **Real sender** | Mail lands in your Gmail **Sent** folder, threads and replies normally. |

---

## Quickstart

Requires Python 3.9+ and a Google account. Budget ~10 minutes, most of it in the Google Cloud Console the first time.

Clone this repo (green **Code** button above for the URL), then:

```bash
cd gmail-mail-merge

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Create your own list and message from the samples.
# -n means "never overwrite", so this is safe to re-run later.
cp -n recipients.sample.csv recipients.csv
cp -n template.sample.txt   template.txt
```

`recipients.csv` and `template.txt` are gitignored — your contacts and your message stay out of git, so you can fork this repo and push changes without ever publishing them. [Formats below](#your-two-input-files).

Then do the [Google Cloud setup](#google-cloud-setup-one-time) below, save `credentials.json` into this folder, and:

```bash
python merge.py                                   # dry-run — prints, sends nothing
python merge.py --send --limit 1 --test-to you@example.com   # one real test to yourself
python merge.py --send                            # send for real
```

The first `--send` opens a browser window for Google sign-in and writes `token.json`. Everything after that is silent.

---

## Google Cloud setup (one time)

You are creating your own private OAuth client. It is free, it stays in Testing mode, and you are the only user.

1. Open the [Google Cloud Console](https://console.cloud.google.com/), signed in **as the account that will send**.
2. Create a project — name it anything, e.g. `personal-mail-merge`.
3. **APIs & Services → Library** → search **Gmail API** → **Enable**.
4. **APIs & Services → OAuth consent screen**
   - User type: **External** (choose Internal only if this is a Workspace org-internal app).
   - App name, support email, developer contact: your own.
   - Scopes: add `https://www.googleapis.com/auth/gmail.send` — and nothing else.
   - **Test users: add your own email address.** Skipping this causes `Error 403: access_denied` at sign-in.
   - Leave it in **Testing**. Do not submit for verification — you don't need it, and see [token expiry](#tokenjson-stops-working-after-a-while) below.
5. **APIs & Services → Credentials → Create credentials → OAuth client ID**
   - Application type: **Desktop app**. Name it anything.
   - **Download JSON.**
6. Save that file in this folder as exactly **`credentials.json`**. It is gitignored — never commit it.

Revoke access at any time under [Google Account → Connections](https://myaccount.google.com/connections), then delete `token.json`.

---

## Your two input files

### `recipients.csv`

Two columns, header row required:

```csv
First Name,Email
Ada,ada@example.com
Grace,grace@example.com
```

- Headers are matched case-insensitively; `firstname`, `first_name`, and `first` all work for the first column.
- Rows with a missing or `@`-less email are skipped silently.
- A blank first name falls back to `there` ("Hi there,").
- **Only these two fields are available as merge fields.** Extra columns in your CSV are ignored — `{Company}` will not be substituted. (See [Extending it](#extending-it).)
- Exporting from a spreadsheet? Save as CSV, UTF-8. A BOM is handled.

### `template.txt`

Plain text. The **first line must start with `SUBJECT:`**; everything after it is the body.

```
SUBJECT: Quick hello from an old contact

Hi {First Name},

...

Best,
Your Name
```

- `{First Name}` is substituted in both the subject and the body. `{{First Name}}` works too, so YAMM-style templates paste in cleanly.
- Plain text only — no HTML, no attachments. Plain text is deliberate: it looks like a real personal email and lands in the inbox more reliably than a marketing HTML blast.

---

## Usage

```bash
python merge.py [options]
```

| Flag | Default | What it does |
|---|---|---|
| `--send` | off | **Actually send.** Without it, everything is a dry run. |
| `--limit N` | all | Process only the **first N rows of the CSV** (the already-sent filter is applied *after* this slice — see the note below). |
| `--test-to ADDR` | — | Redirect every message to `ADDR` instead of the real recipient. Read the warning below. |
| `--delay SECONDS` | `2` | Pause between real sends. |
| `--csv PATH` | `recipients.csv` | Use a different list. |
| `--template PATH` | `template.txt` | Use a different template. |
| `--from ADDR` | authenticated account | Set an explicit `From:` — only works for an address Gmail already lets you send as. |
| `--no-skip-sent` | off | Ignore `sent_log.csv` and re-send to everyone. |
| `--credentials` / `--token` / `--log` | in this folder | Alternate file paths. |

> [!WARNING]
> **`--test-to` does not limit how many messages are sent.** It only rewrites the `To:` header, so `--send --test-to you@example.com` on a 200-row list sends **200 messages to your own inbox**. Always pair it with `--limit 1`.
>
> Test runs are deliberately *not* written to `sent_log.csv` — the real recipient never received anything, so they stay in the queue for your real run.

**`--limit` slices the CSV before skipping already-sent rows.** So on a second run, `--limit 10` means "look at the first 10 rows of the file, send to whichever of them haven't been sent yet" — which can be zero. To send the next 10 unsent people, remove `--limit` and Ctrl-C when you've had enough; the log makes the next run resume where you stopped.

### A sane first campaign

```bash
python merge.py                                              # 1. read the dry-run output
python merge.py --send --limit 1 --test-to you@example.com   # 2. check it in your own inbox
python merge.py --send --limit 3                             # 3. three real ones, eyeball the Sent folder
python merge.py --send                                       # 4. the rest, resuming automatically
```

---

## Files

| File | Committed? | Purpose |
|---|---|---|
| `merge.py` | yes | The whole program. |
| `recipients.sample.csv` / `template.sample.txt` | yes | The examples you copy. Edit your copies, not these. |
| `recipients.csv` / `template.txt` | **gitignored** | Your real list and message. |
| `credentials.json` | **gitignored** | Your OAuth client, from Google Cloud. |
| `token.json` | **gitignored** | Created at first sign-in. Treat it like a password — it can send mail as you. |
| `sent_log.csv` | **gitignored** | Append-only record: email, name, status, Gmail message id, timestamp. |

If you fork this repo, keep those `.gitignore` lines intact. A recipient list is personal data about other people, and a public repo is forever.

---

## Troubleshooting

#### `Error 403: access_denied` at sign-in
Your address isn't listed under **Test users** on the OAuth consent screen. Add it and retry.

#### `token.json` stops working after a while
OAuth clients on a consent screen still in **Testing** issue refresh tokens with a limited lifetime, so you'll periodically be asked to sign in again. Delete `token.json` and re-run — it takes five seconds. See Google's notes on [unverified apps and refresh token expiration](https://developers.google.com/identity/protocols/oauth2#expiration).

#### `FileNotFoundError: ... recipients.csv` (or `template.txt`)
You skipped the two `cp` commands in the Quickstart. Those files are gitignored, so a fresh clone doesn't have them — only the `.sample` versions.

#### `Missing credentials.json`
The download from step 5 isn't in this folder under that exact filename.

#### The browser window never opens / running over SSH
`merge.py` uses a local-redirect OAuth flow, so the **first** sign-in must happen on a machine with a browser. Authorize locally, then copy `token.json` to the remote machine.

#### Sends stop partway with a quota or rate error
You've hit Google's per-account daily send limit — these differ for free Gmail and Workspace accounts, and Google changes them; see [Gmail sending limits](https://support.google.com/mail/answer/22839). Nothing is lost: errors are written to `sent_log.csv` and the next run resumes with whoever is left. Wait 24 hours, or raise `--delay`.

#### Messages land in spam
Plain text, a real subject line, a genuine personal message to people who know you, and a modest volume per day is the whole recipe. This tool cannot fix a cold blast.

---

## Extending it

`merge.py` is ~290 lines with no framework in the way.

- **More merge fields.** `load_recipients()` deliberately narrows each row to `First Name` and `Email`. Pass the full row through instead and `render()` will substitute any `{Column Name}` from your CSV.
- **HTML email.** Swap `msg.set_content(body)` in `build_raw_message()` for `msg.add_alternative(html, subtype="html")`.
- **Attachments, threading, scheduling.** All reachable from the same `EmailMessage` object.

Issues and PRs welcome.

---

## Responsible use

This sends real email to real people from your own address. Only mail people who know you or have a genuine reason to hear from you, honor opt-outs immediately, and stay on the right side of CAN-SPAM, GDPR/PECR, and Gmail's own [bulk sender guidelines](https://support.google.com/mail/answer/81126) — that's on you, not on this script. It is built for reconnecting with your own contacts, not for cold outreach at scale.

## License

[MIT](LICENSE).
