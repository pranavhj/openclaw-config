# LLM Gateway — Integration Guide

HTTP server that lets any app send questions to Claude and store structured data for AI analysis.

**Server:** `http://100.122.101.27:18789` (PC Tailscale IP)
**Auth:** `Authorization: Bearer <token>` (from `~/.openclaw/openclaw.json` → `gateway.auth.token`)
**Start:** `python D:\MyData\Software\openclaw-config\bin\llm-gateway.py`

---

## API Reference

### GET /health (no auth)

```bash
curl http://100.122.101.27:18789/health
```
```json
{"status": "ok", "active_sessions": 0, "projects": ["dairy"]}
```

### POST /ask

Send a question to Claude. Response is synchronous (up to 120s).

```bash
curl -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" \
  -d '{"project": "dairy", "message": "How was my week?"}' \
  http://100.122.101.27:18789/ask
```
```json
{"status": "ok", "response": "Based on your entries...", "duration_ms": 8500}
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `project` | yes | Project slug (e.g. `"dairy"`) |
| `message` | yes | Question or request text |
| `context` | no | `"auto"` (default) = load stored data into prompt. `"none"` = skip data, for simple questions like "what is HTTP?" |
| `fresh` | no | `false` (default) = resume the project's conversation (`claude --continue`). `true` = new conversation each call — for stateless callers (e.g. per-item scoring) so earlier requests cannot leak into the answer. |

**Error responses:**

| Code | Meaning |
|------|---------|
| 401 | Missing or invalid auth token |
| 404 | Unknown project slug |
| 409 | Project already processing (retry after `retry_after_ms`) |
| 429 | Too many concurrent sessions (max 3) |
| 504 | Claude timed out (120s) |

### POST /data/{project}

Store a data entry. Append-only JSONL storage.

```bash
curl -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" \
  -d '{"type": "journal_entry", "data": {"text": "Great day", "mood": "happy", "timestamp": "2026-06-10T08:00:00Z"}}' \
  http://100.122.101.27:18789/data/dairy
```
```json
{"status": "ok", "id": "entry_1718025000000"}
```

**Fields:**

| Field | Required | Description |
|-------|----------|-------------|
| `type` | yes | Data type matching project schema (e.g. `"journal_entry"`) |
| `data` | yes | Object with fields defined in project schema |

### GET /data/{project}

Query stored data.

```bash
curl -H "Authorization: Bearer TOKEN" \
  "http://100.122.101.27:18789/data/dairy?type=journal_entry&limit=10"
```

**Query params:** `type` (filter), `since` (ISO8601 cutoff), `limit` (default 50)

### GET /projects

List all registered projects.

### POST /projects

Register a new project.

```bash
curl -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" \
  -d '{"slug": "fitness", "display": "Fitness Tracker", "schema": {"workout": {"type": "string (required)", "duration_min": "number", "timestamp": "ISO8601 (required)"}}, "instructions": "Track workout frequency and progress."}' \
  http://100.122.101.27:18789/projects
```

---

## Project Structure

Each project lives at `C:\Users\prana\projects\<slug>_llm_gateway\`:

```
dairy_llm_gateway/
  project.json       # Machine config: slug, display name, data schema
  instructions.md    # User-written: how Claude should analyze this project's data
  data/
    journal_entry.jsonl   # One JSON object per line, append-only
    metric.jsonl          # Separate file per data type
```

### project.json (machine config only)

```json
{
  "slug": "dairy",
  "display": "Dairy Journal",
  "schema": {
    "journal_entry": {
      "text": "string (required)",
      "mood": "happy|neutral|sad|anxious|excited",
      "activities": "string[]",
      "timestamp": "ISO8601 (required)"
    }
  }
}
```

Fields marked `(required)` are validated on POST /data — requests missing them get 400.

### instructions.md (user-written analysis prompt)

This is injected into every `/ask` prompt. Tell Claude how to interpret your data:

```markdown
You are a supportive AI journaling companion.

Analyze the journal entries as time series data to understand how I'm doing
across all dimensions — mood, energy, activities, social connections.

When analyzing:
- Look for mood patterns over time (trending up/down, weekly cycles)
- Correlate activities with mood changes
- Highlight positive trends and gently note concerns

Be warm and encouraging. Focus on actionable insights.
```

---

## Android Integration (Java/Kotlin)

### OkHttp Example

```java
// Add to app/build.gradle:
// implementation 'com.squareup.okhttp3:okhttp:4.12.0'

public class AiGateway {
    private static final String BASE = "http://100.122.101.27:18789";
    private static final String TOKEN = "your-token-here";
    private final OkHttpClient client = new OkHttpClient.Builder()
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(120, TimeUnit.SECONDS)  // Claude can take up to 120s
            .build();

    /** Ask Claude a question. Call from background thread. */
    public String ask(String project, String message) throws IOException {
        return ask(project, message, "auto");
    }

    public String ask(String project, String message, String context) throws IOException {
        JSONObject body = new JSONObject();
        body.put("project", project);
        body.put("message", message);
        body.put("context", context);

        Request req = new Request.Builder()
                .url(BASE + "/ask")
                .addHeader("Authorization", "Bearer " + TOKEN)
                .post(RequestBody.create(body.toString(), MediaType.parse("application/json")))
                .build();

        try (Response resp = client.newCall(req).execute()) {
            String json = resp.body().string();
            JSONObject result = new JSONObject(json);

            if (resp.code() == 409) {
                // Project busy — retry after delay
                int retryMs = result.optInt("retry_after_ms", 5000);
                throw new IOException("Busy, retry after " + retryMs + "ms");
            }
            if (!resp.isSuccessful()) {
                throw new IOException("Gateway error " + resp.code() + ": " + result.optString("error"));
            }
            return result.getString("response");
        }
    }

    /** Store a data entry. Call from background thread. */
    public String storeData(String project, String type, JSONObject data) throws IOException {
        JSONObject body = new JSONObject();
        body.put("type", type);
        body.put("data", data);

        Request req = new Request.Builder()
                .url(BASE + "/data/" + project)
                .addHeader("Authorization", "Bearer " + TOKEN)
                .post(RequestBody.create(body.toString(), MediaType.parse("application/json")))
                .build();

        try (Response resp = client.newCall(req).execute()) {
            JSONObject result = new JSONObject(resp.body().string());
            if (!resp.isSuccessful()) {
                throw new IOException("Store failed: " + result.optString("error"));
            }
            return result.getString("id");
        }
    }
}
```

### Usage from Activity

```java
// Store a journal entry
new Thread(() -> {
    try {
        AiGateway gw = new AiGateway();
        JSONObject entry = new JSONObject();
        entry.put("text", "Great run today");
        entry.put("mood", "happy");
        entry.put("activities", new JSONArray(Arrays.asList("running")));
        entry.put("timestamp", Instant.now().toString());
        gw.storeData("dairy", "journal_entry", entry);
    } catch (Exception e) {
        Log.e("Gateway", "Store failed", e);
    }
}).start();

// Ask Claude a question
new Thread(() -> {
    try {
        AiGateway gw = new AiGateway();
        String response = gw.ask("dairy", "How was my mood this week?");
        runOnUiThread(() -> textView.setText(response));
    } catch (Exception e) {
        Log.e("Gateway", "Ask failed", e);
    }
}).start();

// Simple question (no data context needed)
String answer = gw.ask("dairy", "What does serotonin do?", "none");
```

---

## How /ask Works Internally

1. App sends `POST /ask {"project": "dairy", "message": "How was my week?"}`
2. Gateway checks auth, acquires per-project lock
3. Spawns `gateway-delegate.py` which:
   - Loads `project.json` (schema)
   - Loads `instructions.md` (analysis prompt)
   - If `context != "none"`: loads last 7 days / 50 entries from JSONL
   - Builds combined prompt and spawns Claude (Haiku model)
4. Claude responds with analysis
5. Gateway returns `{"status": "ok", "response": "...", "duration_ms": ...}`

**Concurrency:** One Claude session per project at a time. If a project is busy, you get `409` with `retry_after_ms`. Up to 3 projects can run simultaneously.

---

## Creating a New Project for Your App

### Option 1: API

```bash
curl -X POST -H "Authorization: Bearer TOKEN" -H "Content-Type: application/json" \
  -d '{
    "slug": "myapp",
    "display": "My App Name",
    "schema": {
      "my_data_type": {
        "field1": "string (required)",
        "field2": "number",
        "timestamp": "ISO8601 (required)"
      }
    },
    "instructions": "Analyze trends in field1 over time."
  }' \
  http://100.122.101.27:18789/projects
```

### Option 2: Manual

```bash
mkdir -p ~/projects/myapp_llm_gateway/data

# project.json — define your data shape
cat > ~/projects/myapp_llm_gateway/project.json << 'EOF'
{
  "slug": "myapp",
  "display": "My App",
  "schema": {
    "event": {
      "name": "string (required)",
      "value": "number",
      "timestamp": "ISO8601 (required)"
    }
  }
}
EOF

# instructions.md — tell Claude how to use the data
cat > ~/projects/myapp_llm_gateway/instructions.md << 'EOF'
You are analyzing event data from my app.
Look for patterns, anomalies, and trends.
When I ask for a summary, compare recent data to historical baselines.
EOF
```

### Writing Good instructions.md

This is the most important file — it tells Claude **what to do** with your data. Tips:

- Be specific about what patterns matter to you
- Tell Claude the tone you want (clinical vs warm, brief vs detailed)
- Mention time comparisons if relevant ("compare this week to last week")
- Include domain knowledge ("after running, mood usually improves next day")
- Say what's NOT useful ("don't comment on individual entries, focus on trends")

---

## Data Storage Details

- **Format:** JSONL (one JSON object per line), one file per data type
- **Metadata:** Each entry gets `_id`, `_ts` (server UTC), `_type` auto-added
- **Retention:** Append-only, no automatic deletion
- **Size:** For < 500 entries, all recent data is injected into Claude's prompt. For larger datasets, an MCP server will be auto-activated to let Claude query data on demand.
- **Location:** `C:\Users\prana\projects\<slug>_llm_gateway\data\<type>.jsonl`

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Connection refused | Gateway not running. Start with `python bin/llm-gateway.py` |
| 401 Unauthorized | Check token matches `~/.openclaw/openclaw.json` → `gateway.auth.token` |
| 409 Busy | Project has an active Claude session. Retry after `retry_after_ms` |
| 429 Too many sessions | 3 concurrent limit hit. Wait for one to finish |
| Timeout (504) | Claude took > 120s. Try a simpler question or use `context: "none"` |
| Empty response | Check `instructions.md` exists and has useful content |
| Wrong data in response | Verify JSONL entries have `timestamp` field for date filtering |
