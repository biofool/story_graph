# Meta App Review Submission Package

**App Name:** Source Family Public Page Research  
**Requested Feature:** Page Public Content Access  
**App Type:** Business  

---

## 1. App Review Description (Copy & Paste Ready)

```text
This app is a historical research and source-provenance tool that searches and analyses public Facebook Page content related to the Source Family / Father Yod and associated public media history.

It uses Meta’s approved Pages Search and Page Public Content Access capabilities to identify relevant public Pages and analyse or display only public Page metadata, posts, comments, and engagement necessary for human research review.

The app stores limited provenance data: Page name and ID, post or comment ID, canonical URL, public timestamp, limited relevant excerpt, retrieval time, topical tags, and a human-assigned evidence classification. It does not publish automated factual conclusions.

The app does not access personal profiles, friend networks, private groups, private content, or content unavailable through the Graph API. It does not scrape Facebook web pages, automate Facebook’s website UI, use browser cookies, or collect login credentials.

Access is restricted to authorized researchers. Data is retained only for source verification and review and is deletable on request.
```

---

## 2. Screencast Video Guidelines

When submitting the review, Meta requires a screencast demonstrating how the data will be used. Ensure your recording shows:

1. **User / Researcher Interface**: Showing how a researcher initiates a query for public page historical data (e.g. running `03_facebook_research.py` or querying `datasette data/graph.db`).
2. **Graph API Integration**: The request being dispatched using Page Public Content Access to fetch posts and comments from a test Page you administer.
3. **Display of Metadata**: The returned public metadata (Page name, timestamp, post message excerpt, permalink) formatted and displayed for human analysis.
4. **Data Isolation**: Highlighting that only public page posts/comments are reviewed, with clear indications that no private user profiles or friend data are requested.

---

## 3. Testing with Graph API Explorer

Before submitting review, test against a Page you administer:
* **Tool URL**: [https://developers.facebook.com/tools/explorer/](https://developers.facebook.com/tools/explorer/)

### Essential API Queries:
1. **Get Administered Page Access Token**:
   ```http
   GET /me/accounts?fields=id,name,access_token
   ```
2. **Fetch Page Feed Posts**:
   ```http
   GET /{PAGE_ID}/feed?fields=id,message,created_time,permalink_url,from&limit=25
   ```
3. **Fetch Post Comments**:
   ```http
   GET /{POST_ID}/comments?fields=id,message,created_time,from,permalink_url&limit=100
   ```
