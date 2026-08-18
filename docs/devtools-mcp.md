# Meta Developer Tools MCP

> **Model Context Protocol (MCP) Server for the Meta Developer Platform**  
> Source: [https://developers.facebook.com/documentation/mcp/devtools-mcp](https://developers.facebook.com/documentation/mcp/devtools-mcp)

The **Meta Developer Tools MCP** server provides AI coding assistants and agents with a single, secure entry point to interact with the Meta Developer Platform. It enables agents to inspect configurations, track API status, manage webhooks, review app compliance, and query official documentation directly inside your development workflow.

---

## Server Information

| Property | Value |
| :--- | :--- |
| **Endpoint URL** | `https://mcp.facebook.com/devtools` |
| **Transport Protocol** | Streamable HTTP / SSE |
| **Authentication** | OAuth 2.0 (via Meta for Developers account) |
| **Status** | Beta |
| **Tool Namespace** | `devtools_*` (10 exposed tools) |

---

## Key Capabilities & Tools

The server exposes 10 tools designed for day-to-day Meta platform development:

### 1. Public & Discovery Tools (No App Permissions Required)
* **`devtools_discovery`**: Search official Meta developer documentation and API references.
* **`devtools_api_changelog`**: Retrieve API changelogs, version deprecation notices, and RSS update feeds.

### 2. App-Scoped Inspection Tools (Read Scope)
* **`devtools_get_app_configuration`**: Inspect app settings, basic configuration, platform targets (iOS/Android/Web), and security settings.
* **`devtools_get_app_review_status`**: Check App Review submission status, reviewer notes, and data access renewal deadlines.
* **`devtools_get_api_health`**: Monitor Graph API usage, rate limit metrics, error rates, and system health status.
* **`devtools_list_apps`**: List Meta developer apps associated with the authenticated account.

### 3. Management Tools (Manage Scope)
* **`devtools_list_webhooks`**: List active webhook subscriptions and subscribed topics/fields for your apps.
* **`devtools_configure_webhook`**: Create, update, or remove webhook subscription endpoints and event topics.
* **`devtools_test_webhook`**: Trigger test payloads for subscribed webhook topics.
* **`devtools_validate_app_setup`**: Validate app setup against Meta policy guidelines and compliance requirements.

---

## Authentication & Permissions

* **OAuth Flow**: Connects directly using your existing Meta Developer account. No manual storage or management of `App ID` or `App Secret` in client config files is required.
* **Scopes**:
  * **Read Scope**: Granted to view app settings, documentation, review status, and API health.
  * **Manage Scope**: Required for modifying configurations such as webhook subscriptions.
* **Account Granularity**: During OAuth login, you can select which specific apps and business portfolios the AI agent is authorized to interact with.

---

## Client Installation & Setup

### 1. Antigravity Configuration

Add to `mcp_config.json` or `.agents/mcp_config.json`:

```json
{
  "mcpServers": {
    "meta_developer_tools": {
      "serverUrl": "https://mcp.facebook.com/devtools"
    }
  }
}
```

Or via stdio bridge (`mcp-remote`):

```json
{
  "mcpServers": {
    "meta_developer_tools": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.facebook.com/devtools"]
    }
  }
}
```

### 2. Claude Code

Run the following command in your terminal:

```bash
claude mcp add --transport http meta_developer_tools https://mcp.facebook.com/devtools
```

Authenticate by running `/mcp` in Claude Code, selecting `meta_developer_tools`, and completing the browser OAuth prompt.

### 3. Cursor

Add to `.cursor/mcp.json` or through **Cursor Settings > Tools & Integrations > New MCP Server**:

```json
{
  "mcpServers": {
    "meta_developer_tools": {
      "url": "https://mcp.facebook.com/devtools",
      "type": "http"
    }
  }
}
```

### 4. Claude Desktop

In Claude Desktop settings (`claude_desktop_config.json`) or **Settings > Connectors**:

```json
{
  "mcpServers": {
    "meta_developer_tools": {
      "command": "npx",
      "args": ["-y", "mcp-remote", "https://mcp.facebook.com/devtools"]
    }
  }
}
```

---

## Distinction from Other Meta MCP Servers

* **Developer Tools MCP (`https://mcp.facebook.com/devtools`)**: For managing apps, webhooks, compliance, and developer docs.
* **Ads MCP Server (`https://mcp.facebook.com/ads`)**: For managing Meta ad accounts, campaigns, ad sets, catalogs, and performance analytics.
