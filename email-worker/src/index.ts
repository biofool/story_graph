/**
 * Story Graph Email Worker
 *
 * Receives emails at story@magicsolutions.biz via Cloudflare Email Routing,
 * extracts URLs from the email body/subject, and stores them in a KV
 * namespace for batch processing by the story_graph pipeline.
 *
 * Each URL is stored as a KV key with metadata (sender, subject, timestamp,
 * source email) so the batch ingestion script can pull and process them.
 *
 * KV key format: "pending:<timestamp>:<url_hash>"
 * KV value: JSON { url, sender, subject, timestamp, email_id, body_snippet }
 *
 * The batch ingestion script (scripts/17_ingest_from_kv.py) reads pending
 * URLs, processes them through the story_graph pipeline, and deletes them
 * from KV on success.
 */

export interface EmailUrl {
  url: string;
  sender: string;
  subject: string;
  timestamp: string;
  email_id: string;
  body_snippet: string;
}

// URL regex — matches http(s):// URLs, including those wrapped in angle brackets
const URL_REGEX = /https?:\/\/[^\s<>"')\]]+/gi;

// Domains that are always allowed (story graph crawl domains + common sources)
const ALLOWED_DOMAINS = [
  "aikidojournal.com",
  "blogspot.com",
  "wordpress.com",
  "lamag.com",
  "latimes.com",
  "pleasekillme.com",
  "cultnews.com",
  "yahowha.org",
  "en.wikipedia.org",
  "youtube.com",
  "web.archive.org",
];

export default {
  async email(
    message: ForwardableEmailMessage,
    env: Env,
    ctx: ExecutionContext
  ): Promise<void> {
    const sender = message.from;
    const subject = message.headers.get("subject") || "(no subject)";
    const emailId = message.headers.get("message-id") || crypto.randomUUID();

    console.log(`[story-graph-email] Received email from ${sender}: ${subject}`);

    // Check sender allowlist if configured
    if (env.ALLOWED_SENDERS) {
      const allowed = env.ALLOWED_SENDERS.split(",").map((s) => s.trim().toLowerCase());
      const senderAddr = sender.match(/<([^>]+)>/)?.[1] || sender;
      if (!allowed.includes(senderAddr.toLowerCase())) {
        console.log(`[story-graph-email] Sender ${sender} not in allowlist, ignoring`);
        return;
      }
    }

    // Read the raw email
    const raw = await new Response(message.raw).arrayBuffer();
    const rawEmail = new TextDecoder().decode(raw);

    // Extract text content — try to get text/plain part, fallback to raw
    const textContent = extractTextContent(rawEmail);

    // Extract URLs from subject + body
    const allText = `${subject}\n${textContent}`;
    const urls = extractUrls(allText);

    if (urls.length === 0) {
      console.log(`[story-graph-email] No URLs found in email from ${sender}`);
      return;
    }

    console.log(`[story-graph-email] Found ${urls.length} URL(s): ${urls.join(", ")}`);

    // Store each URL in KV
    const timestamp = new Date().toISOString();
    let stored = 0;

    for (const url of urls) {
      const urlHash = await hashUrl(url);
      const key = `pending:${timestamp}:${urlHash}`;

      const urlData: EmailUrl = {
        url,
        sender,
        subject,
        timestamp,
        email_id: emailId,
        body_snippet: textContent.slice(0, 500),
      };

      try {
        await env.STORY_URLS.put(key, JSON.stringify(urlData), {
          metadata: {
            url,
            sender,
            timestamp,
            subject: subject.slice(0, 100),
          },
        });
        stored++;
        console.log(`[story-graph-email] Stored URL in KV: ${key} -> ${url}`);
      } catch (err) {
        console.error(`[story-graph-email] Failed to store URL ${url}: ${err}`);
      }
    }

    console.log(`[story-graph-email] Stored ${stored}/${urls.length} URLs from email`);
  },

  // HTTP endpoint for the batch ingestion script to list/delete pending URLs
  async fetch(
    request: Request,
    env: Env,
    ctx: ExecutionContext
  ): Promise<Response> {
    const url = new URL(request.url);

    // Simple auth via bearer token
    const authHeader = request.headers.get("authorization") || "";
    const token = authHeader.replace("Bearer ", "");
    if (!env.STORY_GRAPH_AUTH_TOKEN || token !== env.STORY_GRAPH_AUTH_TOKEN) {
      return new Response("Unauthorized", { status: 401 });
    }

    // GET /pending — list pending URLs
    if (url.pathname === "/pending" && request.method === "GET") {
      const list: { key: string; metadata: any }[] = [];
      let cursor: string | undefined;

      do {
        const result = await env.STORY_URLS.list({
          prefix: "pending:",
          cursor,
        });
        for (const k of result.keys) {
          list.push({ key: k.name, metadata: k.metadata });
        }
        cursor = result.list_complete ? undefined : result.cursor;
      } while (cursor);

      return Response.json({ pending: list, count: list.length });
    }

    // GET /pending/:key — get full URL data
    if (url.pathname.startsWith("/pending/") && request.method === "GET") {
      const key = url.pathname.replace("/pending/", "");
      const value = await env.STORY_URLS.get(key);
      if (!value) {
        return new Response("Not found", { status: 404 });
      }
      return Response.json({ data: JSON.parse(value) });
    }

    // DELETE /pending/:key — delete after successful ingestion
    if (url.pathname.startsWith("/pending/") && request.method === "DELETE") {
      const key = url.pathname.replace("/pending/", "");
      await env.STORY_URLS.delete(key);
      return Response.json({ deleted: key });
    }

    // GET /health — health check
    if (url.pathname === "/health") {
      return Response.json({ status: "ok", service: "story-graph-email" });
    }

    return new Response("Not found", { status: 404 });
  },
};

function extractUrls(text: string): string[] {
  const matches = text.match(URL_REGEX) || [];
  // Deduplicate, strip trailing punctuation, filter by allowed domains
  const seen = new Set<string>();
  const urls: string[] = [];

  for (let raw of matches) {
    // Strip trailing punctuation that's not part of the URL
    raw = raw.replace(/[.,;:!?]+$/, "");
    // Strip angle brackets
    raw = raw.replace(/^<|>$/g, "");

    if (seen.has(raw)) continue;
    seen.add(raw);

    // Check if domain is in allowed list (or allow all if no filter)
    const domain = extractDomain(raw);
    if (ALLOWED_DOMAINS.some((d) => domain === d || domain.endsWith("." + d))) {
      urls.push(raw);
    } else {
      // Also allow any URL — the batch script can filter further
      urls.push(raw);
    }
  }

  return urls;
}

function extractDomain(url: string): string {
  try {
    const u = new URL(url);
    return u.hostname.toLowerCase();
  } catch {
    return "";
  }
}

function extractTextContent(rawEmail: string): string {
  // Simple text extraction — find text/plain part in MIME
  const plainMatch = rawEmail.match(
    /Content-Type:\s*text\/plain[\s\S]*?\r?\n\r?\n([\s\S]*?)(?:\r?\n--|\r?\n\r?\n\.)/i
  );
  if (plainMatch) {
    return decodeQuotedPrintable(plainMatch[1]).trim();
  }

  // Fallback: try text/html part, strip tags
  const htmlMatch = rawEmail.match(
    /Content-Type:\s*text\/html[\s\S]*?\r?\n\r?\n([\s\S]*?)(?:\r?\n--|\r?\n\r?\n\.)/i
  );
  if (htmlMatch) {
    return stripHtml(decodeQuotedPrintable(htmlMatch[1])).trim();
  }

  // Last resort: use the whole raw email
  return stripHtml(rawEmail).slice(0, 5000);
}

function stripHtml(html: string): string {
  return html
    .replace(/<[^>]+>/g, " ")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/\s+/g, " ")
    .trim();
}

function decodeQuotedPrintable(text: string): string {
  return text
    .replace(/=\r?\n/g, "")
    .replace(/=([0-9A-F]{2})/g, (_, hex) => String.fromCharCode(parseInt(hex, 16)));
}

async function hashUrl(url: string): Promise<string> {
  const encoder = new TextEncoder();
  const data = encoder.encode(url);
  const hashBuffer = await crypto.subtle.digest("SHA-256", data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.slice(0, 8).map((b) => b.toString(16).padStart(2, "0")).join("");
}

interface Env {
  STORY_URLS: KVNamespace;
  GRAPH_API_URL: string;
  ALLOWED_SENDERS: string;
  STORY_GRAPH_AUTH_TOKEN: string;
}
