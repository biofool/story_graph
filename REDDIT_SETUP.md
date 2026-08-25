# Reddit Integration Setup Guide

## Overview

The Reddit integration extracts discussions about the Source Family, Father Yod, Jim Baker, and related topics from subreddits including:
- r/cults
- r/communes  
- r/spirituality
- r/cultsurvivors
- r/exvangelical
- r/hippies
- r/1970s
- r/losangeles

All discussions are ingested into story_graph with proper source attribution.

## Step 1: Create a Reddit App

1. **Log in to Reddit** (your basic account)
   - Go to https://www.reddit.com

2. **Navigate to App Preferences**
   - Go to https://www.reddit.com/prefs/apps
   - Or: Settings → Advanced → App passwords → Scroll to bottom

3. **Create a New App**
   - Click **"Create app"** (button at the bottom of the page)
   - Fill in the form:
     - **Name:** `StorygraphSourceFamilyResearch`
     - **App type:** Select **"script"**
     - **Description:** (optional) "Research tool for Source Family historical discussions"
     - **Redirect URI:** `http://localhost:8080`
   - Click **"Create app"**

4. **Copy Your Credentials**
   
   After creation, you'll see a card with your app info:
   
   ```
   StorygraphSourceFamilyResearch
   ─────────────────────────────
   Personal use script
   ⓘ Client ID: xxxxxxxxxxxxxxxx  ← Copy this
   
   [show]  ← Click to reveal secret
   ```

   - **Client ID** is shown below the app name
   - **Client Secret** — click `[show]` to reveal it
   - **User Agent** — create one: `StorygraphSourceFamily/1.0 by YourRedditUsername`

## Step 2: Add Credentials to `.env`

1. **Copy template to live config:**
   ```bash
   cp .env.example .env
   ```

2. **Edit `.env` and add Reddit section:**
   ```bash
   nano .env  # or your editor
   ```

3. **Fill in the Reddit section** (at the bottom):
   ```env
   # ===================
   # Reddit API (Source Family discussions extraction)
   # ===================
   REDDIT_CLIENT_ID=your_client_id_here
   REDDIT_CLIENT_SECRET=your_client_secret_here
   REDDIT_USER_AGENT=StorygraphSourceFamily/1.0 by YourUsername
   REDDIT_USERNAME=your_reddit_username
   REDDIT_PASSWORD=your_reddit_password
   ```

4. **Save and close** (Ctrl+O, Enter, Ctrl+X for nano)

## Step 3: Install PRAW (Python Reddit API Wrapper)

```bash
# Activate virtual environment
source .venv/bin/activate

# Install PRAW
pip install praw
```

## Step 4: Run the Extractor

```bash
python scripts/06_reddit_integration.py
```

The script will:
1. Search multiple subreddits for Source Family discussions
2. Extract post titles, body text, and top comments
3. Save raw data to `data/reddit_extracts.json`
4. Integrate discussions into story_graph as WORK nodes with source attribution

## Step 5: Verify Integration

```bash
# Check what was added
python3 << 'EOF'
import sqlite3
from pathlib import Path

db = sqlite3.connect("data/graph.db")
cursor = db.cursor()

# Count Reddit sources
cursor.execute("SELECT COUNT(*) FROM sources WHERE platform='reddit'")
print(f"Reddit sources: {cursor.fetchone()[0]}")

# List Reddit discussions
cursor.execute("SELECT id, label FROM nodes WHERE id LIKE 'work-reddit-%' LIMIT 10")
for row in cursor.fetchall():
    print(f"  • {row[1][:60]}...")

db.close()
EOF
```

## Troubleshooting

### "Missing Reddit credentials"
- Check `.env` file exists and has all 5 fields filled
- Verify no spaces around `=` signs
- Restart your terminal to reload environment

### "403 Forbidden" / "Invalid credentials"
- Double-check Client ID and Client Secret (copy exactly)
- Verify Reddit username and password are correct
- Confirm app type was set to "script" (not "web app")

### No results found
- Search terms may not match discussions
- Check subreddit access (some are private)
- Increase search limit in `06_reddit_integration.py`

### PRAW installation fails
- Ensure virtual environment is activated: `source .venv/bin/activate`
- Update pip: `pip install --upgrade pip`
- Then retry: `pip install praw`

## What Gets Extracted

For each discussion found:

**Submission Node** (WORK):
- Title
- Author
- Subreddit
- Score / engagement
- Full post text

**Source Record**:
- Reddit permalink (URL)
- Publication date
- Platform: "reddit"
- Source class: "comment_thread"
- Bias hint: "neutral_ish"

**Comments**:
- Top 10 comments extracted
- Author, text, score
- Integrated into discussion context

## Searching Custom Terms

To search for additional topics, edit `06_reddit_integration.py`:

```python
self.search_terms = [
    "Source Family",
    "Father Yod",
    "Jim Baker cult",
    "Your custom search term here",  # ← Add yours
]
```

Then re-run the script.

## Privacy Notes

- Reddit accounts are public; consider the implications
- Usernames and comments are extracted as-is (public data)
- No personal data beyond what's already public on Reddit
- All extracted data stays local in your story_graph database

## Next Steps

After extracting Reddit discussions:

1. **Review** `data/reddit_extracts.json` for quality
2. **Link** discussions to existing Source Family entities (Father Yod, Jim Baker, etc.)
3. **Extract claims** from comments (disagreements, confirmations, new facts)
4. **Compare** against journalism sources and oral history
5. **Flag** contradictions and unverified claims

---

**Questions?** See `scripts/06_reddit_integration.py` header for additional context.
