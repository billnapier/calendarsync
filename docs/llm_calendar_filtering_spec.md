# Feature Spec: LLM-Powered Smart Calendar Filtering (Revised & Production-Ready)

## 1. Executive Summary

Many public and institutional iCal feeds (such as university course schedules, athletic calendars, or company event feeds) are massive, noisy, and lack native filtering options. 

This feature introduces **LLM-Powered Smart Calendar Filtering** to CalendarSync. Users provide an upstream iCal feed URL along with a natural language filter prompt (e.g., *"Only include exams, assignment deadlines, and CS 101 lectures; exclude social events and office hours"*). CalendarSync periodically ingests the feed, uses an LLM (Gemini Flash on Vertex AI) to evaluate events against the prompt, generates a clean, filtered `.ics` feed, and hosts it statically via Google Cloud Storage (following the established EasyCloud architecture).

A primary architectural requirement is **strict cost optimization and reliability** via multi-layer HTTP/hash caching, atomic file serving, structured batching, and zero-subcollection Firestore design.

---

## 2. User Journey & Experience

### Critical User Journey (CUJ): Creating and Subscribing to a Filtered Feed

```
┌─────────────────┐     ┌───────────────────────┐     ┌────────────────────────┐     ┌────────────────────────┐
│  1. Dashboard   │────>│ 2. Create Smart Filter│────>│  3. Async Processing   │────>│ 4. Subscribe Feed URL  │
│ Click "+ Smart  │     │ Provide Source URL &  │     │ Fetch -> Hash Check    │     │ Copy hosted .ics link  │
│    Filter"      │     │  Natural Lang Prompt  │     │ -> LLM -> Store .ics   │     │ into Google/Apple/etc. │
└─────────────────┘     └───────────────────────┘     └────────────────────────┘     └────────────────────────┘
```

1. **Initiation**: From the CalendarSync dashboard, the user clicks **"+ New Smart Filter Calendar"**.
2. **Configuration Form**: The user inputs:
   - **Calendar Name**: e.g., *"CS 101 & Exams Only"*
   - **Source iCal Feed URL**: e.g., `https://university.edu/calendar/all_events.ics`
   - **Natural Language Prompt**: e.g., *"Include only CS 101 lectures, midterm/final exams, and project submission deadlines. Exclude office hours, student club meetings, and general announcements."*
3. **Initial Pipeline Execution**:
   - The backend validates the source URL (SSRF via `app.security.safe_requests_get` & size checks).
   - Fetches the feed, extracts candidate event metadata into minimal JSON payloads, invokes Vertex AI Gemini in batches, filters original `.ics` VEVENT components, and atomically writes the output `.ics` file and audit JSON to Google Cloud Storage (GCS).
4. **Output & Subscription**:
   - The user is presented with a hosted feed URL: `https://storage.googleapis.com/<bucket>/filtered_calendars/<user_id>/<calendar_id>.ics` (identical pattern to EasyCloud calendars).
   - The dashboard provides a **"Copy Subscription URL"** button and an **"Audit / Debug Log"** tab to view LLM filtering rationale.
5. **Automated Background Maintenance**:
   - Cloud Scheduler regularly triggers background refreshes via Cloud Tasks.
   - If the upstream feed has not changed (verified via ETag 304 or SHA-256 content hash), zero LLM calls occur.
   - If changes are detected, active events are processed in batches of 100.

---

## 3. Architecture & Technical Data Flow

```
                               ┌──────────────────────────────────────────┐
                               │       Upstream iCal Source Feed          │
                               └────────────────────┬─────────────────────┘
                                                    │
                                                    ▼
                               ┌──────────────────────────────────────────┐
                               │       HTTP Fetch & Header Check          │
                               │   (ETag / Last-Modified Validation)      │
                               └────────────────────┬─────────────────────┘
                                                    │
                                           [Has feed changed?]
                                           /                 \
                                    (NO)  /                   \ (YES)
                                         ▼                     ▼
                               ┌───────────────────┐ ┌────────────────────┐
                               │ Skip Execution    │ │ Parse iCal &       │
                               │ (Zero LLM / GCS)  │ │ Filter Date Window │
                               └───────────────────┘ └─────────┬──────────┘
                                                               │
                                                               ▼
                                                     ┌────────────────────┐
                                                     │ Feed SHA-256 Hash  │
                                                     │ Check (Tier 3)     │
                                                     └─────────┬──────────┘
                                                               │
                                                      [Content Changed?]
                                                      /                \
                                               (NO)  /                  \ (YES)
                                                    ▼                    ▼
                                         ┌───────────────────┐ ┌────────────────────┐
                                         │ Update Timestamp  │ │ Batch Events (100) │
                                         │ & Exit            │ │ Sanitize & Truncate│
                                         └───────────────────┘ └─────────┬──────────┘
                                                                         │
                                                                         ▼
                                                               ┌────────────────────┐
                                                               │ Vertex AI Gemini   │
                                                               │ (Structured JSON)  │
                                                               └─────────┬──────────┘
                                                                         │
                                                                         ▼
                                                               ┌────────────────────┐
                                                               │ Rebuild .ics File  │
                                                               │ Write Audit JSON   │
                                                               │ Atomic GCS Upload  │
                                                               └─────────┬──────────┘
                                                                         │
                                                                         ▼
                                                               ┌────────────────────┐
                                                               │ Served statically  │
                                                               │ to Subscribers     │
                                                               └────────────────────┘
```

---

## 4. Technology Selection: Gemini on Vertex AI

**Model Selection:** `gemini-2.5-flash` (or `gemini-1.5-flash`) via the Vertex AI SDK (`google-genai` / `google-cloud-aiplatform`).

**Key Integration Rules:**
1. **Application Default Credentials (ADC):** Authenticates automatically using Cloud Run's service account.
2. **Strict Response Schema Enforcement:** Configured with `response_mime_type="application/json"` and Pydantic response schema models.
3. **Cost Efficiency:** `gemini-2.5-flash` provides ultra-low per-token costs ($0.075 / 1M input tokens).

---

## 5. Data Pipeline (iCal Extraction, Batching & Schema)

Raw `.ics` feeds contain verbose headers, `VTIMEZONE` blocks, line folding, formatted HTML descriptions, and complex metadata. The extraction pipeline cleans and batches events before invoking Gemini.

### Step A: Date Window & Candidate Filtering
To handle recurring events (`RRULE`) correctly without deleting long-running series:
- **Master Recurring Events (`RRULE`):** Compute the effective recurrence range using `DTSTART` and `RRULE` bounds (`UNTIL` or count). If any part of the active recurrence window overlaps `[-30 days, +365 days]`, include the master `VEVENT` in the candidate set.
- **Single-Instance Events:** Include if `start_date` falls within `[-30 days, +365 days]`.

### Step B: Payload Sanitization & Minimal Event Extraction
For candidate events, extract a minimal JSON structure:
- `id`: Native iCal `UID` string (stable across fetches).
- `summary`: Event title string.
- `description`: HTML stripped, truncated to max 300 characters.
- `location`: Location string (if present).
- `start`: ISO timestamp string.
- `end`: ISO timestamp string.
- `recurs`: Human-readable recurrence summary if `RRULE` exists (e.g., `"FREQ=WEEKLY;BYDAY=TU,TH"`).

Omit attendees, organizers, attachments, alarms (`VALARM`), and secondary metadata to minimize token usage.

### Step C: LLM Batching & System Instruction
Events are partitioned into batches of **max 100 events per LLM API call**.

- **System Instruction**:
  > You are a precise calendar filtering engine. Evaluate each calendar event against the user's criteria. You must explicitly evaluate every event provided and indicate whether it should be included or excluded, along with a concise 1-sentence reason.

- **User Payload**:
  - `criteria`: User's natural language filter prompt.
  - `events`: JSON array of sanitized events (max 100 items).

- **Enforced Pydantic Output Schema**:
  ```python
  from pydantic import BaseModel, Field
  from typing import List

  class EventEvaluation(BaseModel):
      id: str = Field(description="The exact native iCal UID provided in the input event")
      include: bool = Field(description="True if the event matches user criteria, False otherwise")
      reason: str = Field(description="Concise 1-sentence explanation for the decision")

  class BatchFilterResponse(BaseModel):
      evaluations: List[EventEvaluation] = Field(description="Explicit evaluations for every event in the batch")
  ```

### Step D: Rebuilding `.ics` Feed & Audit Sidecar
1. **Preserve Timezones:** Retain all `VTIMEZONE` components from the original source feed.
2. **Filter VEVENTs:** Iterate through the original source `icalendar.Calendar` components. Include only `VEVENT` components whose native `UID` received `include: true` from Gemini. Retain all original event properties (`RRULE`, `VALARM`, exact timestamps, attachments) untouched.
3. **Inject Headers:** Set `PRODID: "-//CalendarSync//LLM Smart Filter 1.0//EN"`, `VERSION: "2.0"`, `X-WR-CALNAME: <Name>`, and `X-WR-CALDESC: "Filtered: <Prompt>"`.
4. **Audit Sidecar:** Serialize all `evaluations` into a JSON audit file: `filtered_calendars/<user_id>/<calendar_id>_audit.json`.
5. **Atomic GCS Upload:** Upload `.ics` and `_audit.json` to Google Cloud Storage with `content_type="text/calendar"` and `content_type="application/json"`.

---

## 6. Multi-Tier Cost Optimization & Caching Architecture

To prevent unnecessary LLM invocations and avoid Firestore cost explosions:

### Tier 1: Static Feed Serving (Zero-Cost Read Path)
- Filtered `.ics` feeds are stored in Google Cloud Storage and served statically.
- When Google Calendar / Apple Calendar polls the feed, **zero LLM code or database reads are executed**.

### Tier 2: HTTP Header Caching (ETag & Last-Modified)
- Background workers issue HTTP GET requests with `If-None-Match: <etag>` and `If-Modified-Since: <last_modified>` headers stored in Firestore from the prior fetch.
- On HTTP `304 Not Modified`, execution immediately halts.

### Tier 3: Content Fingerprinting (SHA-256 Hashes)
- If the HTTP response lacks cache headers, compute SHA-256 of extracted event UIDs/summaries (`source_hash`) and prompt (`prompt_hash`).
- If `source_hash == stored_source_hash` and `prompt_hash == stored_prompt_hash`, execution halts without calling Gemini.

### Tier 4: Zero-Subcollection Firestore Design
- Eliminates per-event Firestore sub-collections.
- All calendar state lives in a single document: `filtered_calendars/{calendar_id}`.
- Detailed audit logs are written to static GCS sidecar files (`_audit.json`), eliminating Firestore document bloat and read quota costs.

---

## 7. Data Storage & Schema

### Firestore Collection: `filtered_calendars`

| Field | Type | Description |
| :--- | :--- | :--- |
| `id` | `string` | Document ID (`uuid4()`) |
| `user_id` | `string` | Owner user ID |
| `name` | `string` | Display name given by user |
| `source_url` | `string` | Upstream iCal feed URL |
| `filter_prompt` | `string` | User natural language prompt |
| `prompt_hash` | `string` | SHA-256 hash of `filter_prompt` |
| `gcs_path` | `string` | Storage path (`filtered_calendars/{user_id}/{id}.ics`) |
| `public_url` | `string` | Public GCS subscription URL |
| `audit_url` | `string` | Public GCS audit sidecar URL (`..._audit.json`) |
| `etag` | `string` | Last HTTP `ETag` header |
| `last_modified` | `string` | Last HTTP `Last-Modified` header |
| `source_hash` | `string` | SHA-256 hash of source event data |
| `last_fetched_at` | `timestamp` | Time of last upstream fetch |
| `last_evaluated_at` | `timestamp` | Time of last LLM batch run |
| `total_events_evaluated` | `number` | Event count from last run |
| `total_events_included` | `number` | Filtered event count from last run |
| `status` | `string` | `"active"`, `"degraded"`, `"error"` |
| `last_error` | `string` | Last error message (if status is degraded/error) |
| `last_error_at` | `timestamp` | Timestamp of last error |

---

## 8. Background Synchronization & Tasks Architecture

1. **Cron Dispatcher (`/tasks/update_filtered_calendars_all`)**:
   - Triggered every 60 minutes by Cloud Scheduler.
   - Verifies OIDC task auth (`app.security.verify_task_auth()`).
   - Streams all `filtered_calendars` documents and enqueues Cloud Tasks to `/tasks/update_filtered_calendar_one` with payload `{"calendar_id": id}`.

2. **Task Worker (`/tasks/update_filtered_calendar_one`)**:
   - Verifies OIDC task auth.
   - Fetches upstream feed with `safe_requests_get` and ETag headers.
   - On `304 Not Modified`: Updates `last_fetched_at` and exits (200 OK).
   - On `200 OK`: Evaluates content hashes. If changed, batch processes via Gemini.
   - **Atomic Error Handling:**
     - Builds output `.ics` in memory/temp buffer.
     - Only overwrites public GCS `.ics` if the pipeline completes with 100% success.
     - On error: Keeps existing GCS `.ics` untouched, sets `status: "degraded"` in Firestore, logs structured JSON error, and returns 500 to trigger Cloud Task retry limits.

---

## 9. Security & Governance

- **SSRF & Size Protections:** All upstream fetches must use `app.security.safe_requests_get` (blocking private IPs, loopback, and enforce 10MB size limits & 10s timeouts).
- **Task Authentication:** Task endpoints verify OIDC bearer tokens using `app.security.verify_task_auth()`.
- **CSRF Protection:** Web UI forms for creation, edit, and deletion use `verify_csrf_token()`.
- **Feed URL Privacy:** Feed URLs follow `filtered_calendars/{user_id}/{calendar_id}.ics` where `calendar_id` is an unguessable UUID. Users can delete or re-create feeds from the dashboard at any time.
