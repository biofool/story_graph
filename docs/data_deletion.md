# User Data Deletion Instructions

**Application Name:** Source Family Public Page Research  
**Contact:** research@storygraph.local

## Data Deletion Request Process

The **Source Family Public Page Research** application does not maintain user accounts or personal profile records. However, in compliance with Meta Platform Policies and data privacy regulations, Page administrators or individuals whose public posts have been cited in research records may request the removal of their data.

### How to Request Deletion:
1. **Email Request**: Send an email to `research@storygraph.local` (or your project contact email) with the subject line: `Data Deletion Request - Source Family Research`.
2. **Include Identifying Information**:
   - The Facebook Page ID or URL.
   - The specific Post ID, Comment ID, or Permalink to be removed.
3. **Processing Timeline**:
   - All requests are acknowledged within 48 hours.
   - Associated graph nodes, edges, raw excerpts, and database records will be permanently purged within 14 calendar days.
   - A confirmation email with a deletion confirmation code will be provided once completed.

### Automated Deletion Callback
For automated deletion callback integrations:
- **Callback URL**: `https://<YOUR_DOMAIN>/api/facebook/deletion-callback`
- Returns standard JSON response with confirmation code and status check URL as required by Meta Platform Terms.
