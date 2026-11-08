# Wortklar

**Wortklar** is a German → English dictionary web application tailored for an **A1 learner**. It delivers fast, responsive search, clear plain-English definitions, essential A1 grammatical indicators (noun articles, plural forms, verb principal parts, auxiliary verbs), authentic bilingual examples, and an on-demand **Check Wiktionary Online** research action with optional **Gemini AI explanation**.

The application operates with **one app process** and **one SQLite database file**, bound locally to the loopback interface (`127.0.0.1:5000`), with debug mode disabled for normal use.

---

## Architecture & Technology Stack

- **Backend**: Python 3.9+ with [Flask](https://flask.palletsprojects.com/)
- **Database**: [SQLite](https://www.sqlite.org/) via Python's standard library `sqlite3` module
- **Frontend**: Single-page application using vanilla HTML5, semantic CSS3, and modern JavaScript (no external build tooling or bundler required)
- **Deployment**: Loopback interface (`127.0.0.1:5000`), single app process, debug mode disabled
- **Online Research (R5)**: MediaWiki Action API with allowlisted endpoints (`de.wiktionary.org`, `en.wiktionary.org`) and policy-compliant User-Agent
- **AI Stage (Optional R5)**: Server-side official [`google-genai`](https://github.com/googleapis/python-genai) SDK with strict Pydantic structured output

---

## Real Dictionary Data & Attribution

Wortklar is powered by real lexicographical datasets extracted via **Kaikki / Wiktextract**:

1. **English Wiktionary (German Subset)**:
   - Source: [Kaikki German Dataset](https://kaikki.org/dictionary/German/index.html) (`kaikki.org-dictionary-German.jsonl.gz`)
   - SHA-256: `b6b30cf2710b82b1...` | Snapshot Date: `2026-10-30`
   - Records processed: 371,793 | Skipped: 0
2. **German Wiktionary (Deutsch Supplement)**:
   - Source: [Kaikki Deutsch Dataset](https://kaikki.org/dewiktionary/Deutsch/index.html) (`kaikki.org-dictionary-Deutsch.jsonl.gz`)
   - SHA-256: `6ae7b8bd...` | Snapshot Date: `2026-11-01`
   - Records processed: 1,023,903 | Skipped: 0
3. **Database Totals**:
   - Total Lemmas: **1,038,226**
   - Total Attested Forms: **4,750,457**
   - Search Index Entries: **5,788,683**
   - Final Database Size: **3,904.2 MB**

### Attribution and License
- Dictionary content is sourced from **Wiktionary** (Wiktionary contributors, Wikimedia Foundation) and processed by **Wiktextract** ([Tatu Ylönen](https://github.com/tatuylonen/wiktextract)).
- Content is licensed under the [Creative Commons Attribution-ShareAlike 4.0 International License (CC BY-SA 4.0)](https://creativecommons.org/licenses/by-sa/4.0/) and GNU Free Documentation License (GFDL), in accordance with [Wikimedia Terms of Use](https://foundation.wikimedia.org/wiki/Terms_of_Use?useformat=mobile).
- Source text is rendered strictly as text with no upstream HTML injection. Entries link directly to their source Wiktionary editions. When German-edition records lack an English translation, the interface clearly shows *"English meaning unavailable"* rather than treating German definitions as English.

---

## Installation & Quick Start

### Prerequisites
- Python 3.9 or higher
- Git

### macOS / Linux

```bash
# 1. Clone or navigate into repository
cd /path/to/german

# 2. Create and activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Bootstrap real dictionary data (downloads and builds wortklar.db)
python3 bootstrap.py

# 5. (Optional) Configure Gemini API key for AI-assisted explanations:
export GEMINI_API_KEY="your-api-key-here"
export GEMINI_MODEL="gemini-3.1-flash-lite"

# 6. Start the web application
python3 run.py
```

Open your browser at: **`http://127.0.0.1:5000`**

### Windows (Command Prompt / PowerShell)

```cmd
:: 1. Navigate into repository
cd \path\to\german

:: 2. Create and activate virtual environment
python -m venv .venv
.venv\Scripts\activate

:: 3. Install dependencies
pip install -r requirements.txt

:: 4. Bootstrap dictionary data
python bootstrap.py

:: 5. (Optional) Configure Gemini API key
set GEMINI_API_KEY="your-api-key-here"
set GEMINI_MODEL="gemini-3.1-flash-lite"

:: 6. Start the web application
python run.py
```

Open your browser at: **`http://127.0.0.1:5000`**

---

## R1–R4 Search & Grammar Rules

1. **Four-Letter Rule**: Autocomplete suggestion dropdown appears strictly after the **4th typed letter** (counted using trimmed Unicode NFC-normalized characters). Typing fewer than 4 letters triggers **no network request** and renders no dropdown. An explicit `<Enter>` or *Search* button click looks up words of **any length** (`in`, `Ei`, `bin` work immediately).
2. **Keyboard Suggestion List**: Displays up to 8 selectable German results ranked by exact case, case-only, and literal prefixes. Does not modify query unless explicitly selected. Supports <kbd>↑</kbd> / <kbd>↓</kbd> arrows, <kbd>Enter</kbd>, and <kbd>Escape</kbd>. Typing is debounced (120ms) and protected against stale out-of-order network responses.
3. **Spelling Assistance & Lookalikes**:
   - `schon` ("already") and `schön` ("beautiful") never overwrite each other or get labeled typos; both cross-reference each other as lookalikes.
   - `shcön` suggests `schön` (adjacent transposition typo).
   - `hauser` surfaces `Häuser → Haus` ("missing umlaut: a → ä").
   - `Masse` ("mass") and `Maße` ("measurements") appear as distinct valid entries.
   - Decomposed Unicode umlauts (NFD) normalize seamlessly to NFC.
4. **Grammar & Meanings**:
   - **Nouns**: Nominative singular with article (`der`, `die`, `das`), nominative plural with `die`, gender, plural status (`has_plural`, `no_plural`, `plural_only`, `form unavailable`), unchanged plurals (`der Lehrer / die Lehrer`), and distinct homograph separation (`das Band` ribbon vs `die Band` music group).
   - **Verbs**: Infinitive, 3sg present (`geht`), simple past (`ging`), past participle (`gegangen`), auxiliary (`haben`, `sein`), separable and reflexive tags, full person/number conjugation tables.
   - **Adjectives**: Base form, comparative, superlative (`gut → besser → am besten`), strong/weak/mixed declension tables.
   - **Strictly No Invented Data**: Unsupported cells show "—".

---

## R5 Check Wiktionary Online & Gemini Integration

### Manual Online Wiktionary Check
- When a searched word is missing locally (or when looking up additional forms on an existing entry), users can click **"Check Wiktionary Online"** / **"Check Wiktionary for updates"**.
- **The local result remains visible** while the online check runs.
- The server retrieves dictionary evidence directly using allowlisted MediaWiki Action API endpoints (`de.wiktionary.org`, `en.wiktionary.org`) and policy-compliant User-Agent.
- Validates the page title and actual German language section before reading (`== {{Sprache|Deutsch}} ==` or `==German==`).
- Parses evidence into bounded, numbered plain-text records (`[Evidence #1]`, `[Evidence #2]`) with revision id and canonical source URL.
- Facts are rendered in a dedicated **"Online dictionary result"** card.

### Optional Gemini AI Stage
- Configured via server-side environment variables `GEMINI_API_KEY` and `GEMINI_MODEL` (default: `gemini-3.1-flash-lite`).
- **Zero Exposure**: The API key is kept strictly out of the repository, client-side code, URLs, and logs.
- Uses the official `google-genai` SDK with strict Pydantic structured output (`GeminiExplanationSchema`).
- Schema contains **NO** article, plural, conjugation, source URL, or evidence creation fields (those come solely from verified Wiktionary data).
- The prompt sends only the requested word and the numbered evidence records as untrusted data.
- Server validates that referenced `evidence_ids` match the provided evidence records, stripping any hallucinated IDs.
- Labeled as **"AI-assisted explanation"**, strictly separate from dictionary facts.
- **Fail-Safe Operation**: If `GEMINI_API_KEY` is absent, or if 401/403, 429 quota, timeout, or model unavailability occurs, local lookup and Wiktionary online facts continue working without interruption.
- Typing makes **zero external calls**. Cross-origin requests are blocked.

---

## Verification & Test Results

### 1. Regression Test Suite
Run the regression tests:
```bash
python3 -m unittest tests/test_wortklar.py
```
**Results**:
- Ran 8 tests in 51.3s: **OK**
- `test_01_database_metadata_and_integrity`: PASSED (SQLite integrity check verified, 1,038,226 lemmas, 4,750,457 forms).
- `test_02_four_letter_rule`: PASSED (`hau` returns no list; `haus` returns suggestions; `Ei` and `in` work directly).
- `test_03_noun_basics`: PASSED (`das Haus` / `die Häuser` and `house`; `Häuser → Haus`; `der Lehrer` / `die Lehrer` retains unchanged plural).
- `test_04_separate_noun_meanings`: PASSED (`das Band` ribbon vs `die Band` music group separated).
- `test_05_spelling_assistance_and_lookalikes`: PASSED (`schon` vs `schön`, `shcön` -> `schön`, `hauser` -> `Häuser`, `Masse` vs `Maße`, decomposed NFD umlauts, word-start typo `xhaus`).
- `test_06_grammar_forms_and_tables`: PASSED (`ging → gehen`, `bin → sein`, `gegangen`, `gut → besser → am besten`, verb conjugation tables).
- `test_07_no_invented_data`: PASSED (`Durst` no-plural, `Eltern` plural-only, unknown gibberish string returns no invented facts).
- `test_08_interrupted_refresh_resilience`: PASSED (interrupted refresh preserves intact database).

### 2. Performance & Responsiveness Benchmark
Run the responsiveness benchmark on the full 3.9 GB database:
```bash
python3 tests/benchmark.py
```
**Hardware**: Apple Silicon (arm64), macOS 15.5, Python 3.9.6  
**Query Set**: 48 representative local queries (prefixes, umlauts, verbs, nouns, forms) across 3 warm iterations (144 total requests).  
**Actual Latency Results**:
- Min Latency: **0.48 ms**
- Average Latency: **7.72 ms**
- Median (p50): **3.35 ms**
- p90 Latency: **20.05 ms**
- **p95 Latency: 38.48 ms** (Target: < 200 ms — **PASSED**)
- Max Latency: **85.35 ms**

### 3. Headless Browser Verification
Run rendered browser tests in headless Google Chrome:
```bash
python3 tests/test_browser.py
```
**Results**:
- `01_desktop_first_use.png`: First-use view with learner instructions (740x900)
- `02_desktop_haus.png`: `Haus` lookup with core forms box, senses, examples, and more grammar disclosure (740x1100)
- `03_desktop_band_homographs.png`: `das Band` and `die Band` distinct entry cards (740x1200)
- `04_desktop_gehen_verb.png`: Verb forms and conjugation tables (740x1200)
- `05_mobile_haus.png`: Mobile-width layout at 375px viewport (375x812)
- `06_mobile_band.png`: Mobile-width homographs layout (375x812)
- `07_desktop_did_you_mean.png`: Typo assistance for `shcön` -> `schön` (740x900)
- `08_desktop_no_match_check_btn.png`: No-match state with "Check Wiktionary Online" action button (740x900)
- Rendered DOM checks: Headword, article, English glosses, and online check buttons verified.

### 4. R5 Online Wiktionary & Gemini Tests
Run the R5 online test suite:
```bash
python3 -m unittest tests/test_r5_online.py
```
**Results**:
- Ran 10 tests in 3.3s: **OK**
- Live MediaWiki API request to `de.wiktionary.org` for `Kummerspeck`: PASSED (rev 10644352, masculine noun, no plural, definitions, 6 bounded evidence records).
- Missing-word path with omitted entry database (`test_omitted.db`): PASSED (local lookup returns no match, online check fetches live entry, local db unaffected).
- Wrong-language rejection: PASSED (`bonjour` rejected as `non_german_page`).
- Nonexistent entry: PASSED (`qxjzvk987nonsenseword` returned `not_found`).
- Bounded capitalization: PASSED (`kummerspeck` resolved to `Kummerspeck`).
- Cross-origin blocking: PASSED (`Sec-Fetch-Site: cross-site` rejected with 403 Forbidden).
- Gemini Provider Smoke Test: Evaluated cleanly. `GEMINI_API_KEY` was absent in the current environment; verified `ai_status == "gemini_disabled"` and marked **LIVE GEMINI VERIFICATION PENDING**.
- Bad evidence IDs validation: PASSED (model hallucinated ID 999 stripped by server; only valid ID 1 accepted).
- Error resilience: PASSED (simulated 429 quota error and timeout handled cleanly).
- Zero external requests during typing: PASSED (autocomplete queries only SQLite).

### 5. R6 Hosted Mode, Security & Mobile Verification
Run the R6 hosted mode integration test suite:
```bash
python3 -m unittest tests/test_r6_hosted.py
```
**Results**:
- Ran 10 tests in 1.85s: **OK**
- `test_fails_closed_missing_secret_key`: PASSED (raises `RuntimeError` on missing `SECRET_KEY`).
- `test_fails_closed_missing_password_hash`: PASSED (raises `RuntimeError` on missing `WORTKLAR_PASSWORD_HASH`).
- `test_local_mode_remains_unauthenticated`: PASSED (offline local mode operates without login).
- `test_minimal_readiness_healthz_endpoint`: PASSED (`GET /healthz` returns `{"status":"ok"}` with 200 OK and leaks zero metadata, schema, or content).
- `test_healthz_fails_when_db_missing`: PASSED (returns 503 when database is absent).
- `test_logged_out_requests_blocked`: PASSED (`/` redirects to `/login`; `/api/status`, `/api/suggest`, `/api/lookup`, `/api/check_online` return 401 Unauthorized).
- `test_login_csrf_and_invalid_attempts_with_rate_limiting`: PASSED (CSRF enforcement verified; 4 invalid attempts return 401; 5th invalid attempt triggers 15-minute rate-limiting lockout with 429 Too Many Requests).
- `test_authenticated_session_flow_and_logout`: PASSED (valid login redirects to `/`, renders Private session badge, enables autocomplete/lookup/research, and `/logout` clears session).
- `test_sqlite_read_only_enforcement`: PASSED (`get_db_connection(read_only=True)` enforces `PRAGMA query_only = ON` and blocks any write operation with `OperationalError`).
- `test_server_restart_instant_readiness_no_reimport`: PASSED (restart takes 0.003s < 0.2s without reimporting).

Run the headless Google Chrome R6 browser tests:
```bash
PYTHONPATH=. python3 tests/test_browser_r6.py
```
**Results**:
- `09_desktop_login.png`: Clean login card at 740px viewport (57.6 KB).
- `10_mobile_login.png`: Mobile login card at 375px viewport (46.6 KB).
- `11_desktop_hosted_session.png`: Authenticated session on desktop showing Private badge, logout button, and `Haus` results (116.6 KB).
- `12_mobile_hosted_session.png`: Authenticated mobile view at 375px viewport (75.0 KB).
- `13_mobile_virtual_keyboard_simulation.png`: Mobile viewport with virtual keyboard open (375x500); search input and result cards stay readable and accessible via `scroll-margin-top: 24px` (48.7 KB).
- `14_mobile_grammar_table_scroll.png`: Irregular verb `gehen` with horizontal touch scroll wrapper (`-webkit-overflow-scrolling: touch`) verified (62.7 KB).
- Input attributes verified: `autocorrect="off"`, `autocapitalize="none"`, `spellcheck="false"`, `autocomplete="off"` prevent mobile phones from auto-correcting German vocabulary or changing casing.

---

## R6 Hosted Deployment Guide (Render Free Web Service)

Wortklar is fully configured for zero-cost hosting on a **Render Free Web Service**, providing a single private HTTPS URL (`https://<service-name>.onrender.com`) for both your mobile phone and your laptop—even when your laptop is turned off.

### Free Tier Characteristics & Limits
- **Instance Plan**: Free ($0/month, no payment method required).
- **Subdomain**: Included free `onrender.com` subdomain with automatic managed HTTPS.
- **Provider Cold Start**: Render automatically spins down free services after **15 minutes of inactivity**. When a new request arrives, the service wakes up from a cold start in **~50 to 60 seconds**. Once awake, lookups respond in under 40 milliseconds.
- **Free Limits**: 750 free instance hours per month, 512 MB RAM, and standard build pipeline timeouts (~15 minutes).
- **RAM Optimization**: The packaged 3.9 GB SQLite index is queried strictly in read-only mode (`mode=ro`, `PRAGMA query_only = ON`) with SQLite cache capped at 16 MB (`PRAGMA cache_size = -16000`). SQLite pages data on-demand from disk, keeping memory consumption well below Render's 512 MB limit.
- **Internet vs. Offline**:
  - The hosted Render URL requires an internet connection on phone and laptop.
  - The optional laptop copy (`python3 run.py` on loopback `127.0.0.1:5000`) works 100% offline.

---

### Step-by-Step Setup Instructions for Owner

#### Step 1: Create a Private GitHub Repository
1. In your local terminal, initialize and commit the Wortklar codebase:
   ```bash
   git init
   git add .
   git commit -m "Wortklar dictionary app (R1-R6)"
   ```
2. Create a private repository on GitHub (using GitHub CLI or github.com):
   ```bash
   # Via GitHub CLI:
   gh repo create wortklar --private --source=. --push
   
   # Or via browser:
   # 1. Create a new private repository named "wortklar" on github.com
   # 2. Push your code:
   git remote add origin https://github.com/<your-username>/wortklar.git
   git branch -M main
   git push -u origin main
   ```

#### Step 2: Generate Owner Secrets
Run the local generation helper to create your owner password hash and a session secret key:
```bash
# 1. Generate password hash:
python3 hash_password.py "YourStrongOwnerPasswordHere!"

# 2. Generate a secure 64-character signing secret:
python3 -c "import secrets; print('SECRET_KEY=' + secrets.token_hex(32))"
```

#### Step 3: Deploy on Render
1. Sign up for a free account at [render.com](https://render.com) (no credit card required).
2. Click **New +** $\rightarrow$ **Blueprint** (or **Web Service**):
   - Connect your private GitHub repository `wortklar`.
   - If using **Blueprint**, Render automatically reads `render.yaml` with all settings pre-configured!
3. If setting up manually as a **Web Service**:
   - **Name**: `wortklar` (or your preferred name)
   - **Language / Runtime**: `Python 3`
   - **Branch**: `main`
   - **Region**: `Oregon (US West)` or `Frankfurt (EU Central)`
   - **Plan**: `Free`
   - **Build Command**: `pip install -r requirements.txt && python build.py`
   - **Start Command**: `gunicorn -w 2 -b 0.0.0.0:$PORT "wortklar.app:create_app()"`
   - **Health Check Path**: `/healthz`
4. Under **Environment Variables**, add:
   - `HOSTED_MODE`: `true`
   - `SECRET_KEY`: `<the 64-character hex key generated in Step 2>`
   - `WORTKLAR_PASSWORD_HASH`: `<the scrypt/pbkdf2 hash generated in Step 2>`
   - `GEMINI_MODEL`: `gemini-3.1-flash-lite` (optional)
   - `GEMINI_API_KEY`: `<your Google AI Studio key>` (optional, keeps key strictly out of Git)
5. Click **Create Web Service**.

#### Step 4: Build Execution & Cleanup
- During deployment, Render runs `build.py`.
- It streams the Wiktionary datasets, constructs the full 3.9 GB index inside the build output container, verifies SQLite integrity, and deletes temporary `.gz` scratch archives to stay within build disk limits.
- On completion, Render packages the container and starts Gunicorn with 2 workers.
- The readiness endpoint `/healthz` passes, and the service becomes `Live`.

#### Step 5: Bounded Fallback (Private GitHub Release Asset)
If the build environment ever experiences network restrictions reaching Kaikki.org:
1. Compress your locally verified database:
   ```bash
   gzip -c wortklar.db > wortklar.db.gz
   ```
2. Upload `wortklar.db.gz` to a private GitHub Release in your repository:
   ```bash
   gh release create v1.0.0 wortklar.db.gz --title "Wortklar Prebuilt Index v1.0.0"
   ```
3. In your Render Dashboard Environment Variables, set:
   - `RELEASE_ASSET_URL`: `https://github.com/<owner>/wortklar/releases/download/v1.0.0/wortklar.db.gz`
   - `RELEASE_ASSET_SHA256`: `<sha256 of wortklar.db.gz>`
   - `GITHUB_TOKEN`: `<fine-grained Personal Access Token with read-only Contents permission>`
4. `build.py` will automatically stream download, verify the checksum, decompress, and validate the full index without data trimming or paid add-ons.

---

### Accessing Wortklar on Phone & Laptop

Once deployed, Render provides your unique private URL:
`https://<your-service-name>.onrender.com`

1. **On your Laptop**:
   - Open `https://<your-service-name>.onrender.com` in your desktop browser.
   - Enter your owner password to log in.
   - Your session is saved in an `HttpOnly`, `SameSite=Lax`, `Secure` cookie.
2. **On your Phone (iOS Safari / Android Chrome)**:
   - Open the exact same URL: `https://<your-service-name>.onrender.com`.
   - Enter your owner password.
   - Bookmark the page or tap **"Add to Home Screen"** for full-screen app-like access.
   - When typing on the mobile keyboard, autocapitalization and autocorrection are disabled so German words (including lowercase forms like *gehen*, *ging*, *schön*) are never altered by your phone.
   - If the app has been idle for more than 15 minutes, allow ~50 seconds for the Render free instance to spin up.

---

## Requirements and Verification Map

| Requirement | Prompt | Evidence Expected | Current Status | Verification Details |
| :--- | :---: | :--- | :---: | :--- |
| **R1 · Broad real-data import** | 1 | Dataset checksums, coverage counts, integrity and refresh checks | **VERIFIED** | 1,038,226 lemmas, 4,750,457 forms, 0 skipped, SHA-256 recorded, atomic swap tested (`test_01`, `test_08`). |
| **R2 · Autocomplete, spelling & forms** | 1 | 4-letter rule, short words, reverse-forms, typos, lookalikes | **VERIFIED** | 4-letter threshold strictly enforced, short words (*in*, *Ei*, *bin*) work, `schon` vs `schön` preserved, `shcön` $\rightarrow$ *schön* (`test_02`, `test_05`). |
| **R3 · Meanings & grammar** | 1 | Sample entries, noun/verb/adj tables, articles, unchanged plurals | **VERIFIED** | Noun tables with definite articles, unchanged plurals (*der Lehrer*), verb principal parts, comparative/superlative tables (`test_03`, `test_04`, `test_06`). |
| **R4 · Reliable local workflow** | 1 | Offline, keyboard, narrow screen, benchmark timings | **VERIFIED** | Loopback binding (`127.0.0.1:5000`), p95 server latency = 38.48 ms (< 200ms target), headless browser screenshots (`01`–`08`). |
| **R5 · Online research & Gemini** | 2 | Live Wiktionary check, failure tests, Gemini provider smoke test | **VERIFIED** | Live MediaWiki check passed (rev 10644352 `Kummerspeck`), 429/timeout resilience, cross-origin blocking; Gemini marked **LIVE PENDING** (SDK adapter & ID validation unit-verified). |
| **R6 · Private phone & laptop access** | 3 | Protected HTTPS URL, full-index restart, mobile/desktop checks | **VERIFIED (LOCAL) / PENDING (RENDER DEPLOY)** | 10/10 automated tests passed, Gunicorn 2-worker WSGI boot passed, read-only SQLite enforced, CSRF & 5-attempt rate limit verified, Chrome screenshots (`09`–`14`). Live Render URL and physical phone verification pending owner deployment. |

