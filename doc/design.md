# CalendarSync Design Document

## Overview

CalendarSync is a cloud-based service designed to aggregate events from multiple sources into a single, unified destination calendar. It serves users who manage disjointed schedules across various platforms (e.g., work Outlook, personal Google Calendar, shared iCloud calendars) and desire a single view of their availability.

## High-Level Architecture

The system is built as a Flask web application deployed on Google Cloud Run. It leverages Google Cloud Platform services for identity, data storage, background processing, and observability.

### Components

1.  **Web Application (Flask):**
    *   Serves the frontend UI (HTML, CSS, JS) and handles user interactions (creating, editing, deleting, running syncs).
    *   Provides routes for OAuth authentication (`app/auth/routes.py`).
    *   Manages "EasyCloud" virtual calendars (`app/easycloud/routes.py`).
    *   Provides webhook endpoints for background tasks (`app/main/routes.py`).

2.  **Authentication & Identity (Google Identity Services / OAuth 2.0):**
    *   Users sign in using Google Identity Services (GIS).
    *   The app requests OAuth 2.0 scopes specifically for offline access (`access_type="offline"`) to the user's Google Calendar (`https://www.googleapis.com/auth/calendar`).
    *   Refresh tokens are securely stored in Firestore to enable background synchronization without active user presence.

3.  **Database (Firestore):**
    *   A NoSQL document database used to store application state.
    *   **Collections:**
        *   `users`: Stores user profile data and Google OAuth refresh tokens.
        *   `syncs`: Stores configuration for each synchronization job (sources, destination, user ID, last run time).
        *   `easycloud_calendars`: Stores metadata for custom uploaded calendars.

4.  **Background Processing (Cloud Tasks & Cloud Scheduler):**
    *   **Cloud Scheduler:** Acts as a cron job, periodically calling the `/tasks/sync_all` dispatch endpoint.
    *   **Cloud Tasks:** The dispatcher iterates through all active `syncs` in Firestore and enqueues an HTTP task to the `/tasks/sync_one` worker endpoint for each job. This decouples the cron trigger from the execution and provides automatic retries and rate-limiting.

5.  **Storage (Google Cloud Storage):**
    *   Used by the EasyCloud feature to store generated `.ics` files that can be publicly shared or used as sources for syncs.

## Core Logic & Data Flow

### The Sync Process (`app/sync/logic.py`)

The heart of the application is the `sync_calendar_logic` function.

1.  **Configuration Retrieval:** Retrieves the sync configuration (sources, destination, user ID) from Firestore.
2.  **Credential Refresh:** Retrieves the user's refresh token from Firestore and instantiates a Google Calendar API client.
3.  **Source Data Fetching (`_fetch_source_events`):**
    *   Iterates through configured sources (iCal URLs or Google Calendar IDs).
    *   Employs a ThreadPoolExecutor to fetch sources in parallel.
    *   Streams and parses iCal URLs (using the `icalendar` library).
    *   Filters events based on a 13-month rolling window (30 days past to 365 days future) to optimize processing, while retaining master `RRULE` definitions to avoid breaking recurring series.
    *   Deduplicates sources to prevent redundant network calls.
4.  **Destination State Fetching (`_get_existing_events_map`):**
    *   Queries the destination Google Calendar to map `iCalUID`s (the unique identifier for an event in the source) to the destination's internal `eventId`.
    *   Uses Google Calendar API batching for efficiency.
5.  **Reconciliation & Upsert (`_batch_upsert_events`):**
    *   Constructs the Google Calendar API request body for each source event. Appends prefixes to the event summary (e.g., `[Work] Meeting`).
    *   Determines if an event is an Insert (new) or Update (existing), based on the `existing_map`.
    *   Batches the operations into chunks of 50 and executes them against the Google Calendar API, optionally in parallel threads.

### EasyCloud Calendars

EasyCloud allows users to manually upload `.ics` files to create hosted calendars.

1.  **Creation:** A metadata document is created in Firestore, and an empty `.ics` file is uploaded to Cloud Storage.
2.  **Upload:** Users upload a `.ics` file. The server parses the file, either merges it with the existing events or replaces them, and updates the `.ics` file in Cloud Storage.

## Security Considerations

*   **OAuth Scopes:** The application requests the minimum necessary scopes to read and write calendars.
*   **CSRF Protection:** All state-changing POST endpoints are protected by CSRF tokens generated in `app.utils`.
*   **Input Sanitization:** URL validation (`app.security.validate_url`) prevents Server-Side Request Forgery (SSRF) when users input arbitrary iCal URLs.
*   **DoS Protection:** iCal fetching (`safe_requests_get`) enforces timeouts and strict size limits (10MB) to prevent malicious feeds from exhausting server resources.
*   **Logging:** Sensitive data (like credentials in URLs) are stripped before logging (`clean_url_for_log`).
*   **Task Authentication:** Endpoints triggered by Cloud Tasks verify the OIDC token of the invoker to ensure they cannot be triggered publicly.

## Future Development & Extensibility

*   **Rule Engine:** Implement filtering and transformation rules (e.g., "Exclude events titled 'Focus Time'", "Mask all event titles as 'Busy'").
*   **Webhooks:** Support inbound webhooks to trigger syncs immediately upon source changes, reducing reliance on polling.
*   **More Integrations:** Add native support for Microsoft Graph API (Outlook) or CalDAV to avoid relying solely on public `.ics` links for those platforms.