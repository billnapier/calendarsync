# CalendarSync Critical User Journeys (CUJ)

This document outlines the core workflows a user takes through the CalendarSync application.

## CUJ 1: Onboarding and Authentication

**Goal:** A new user accesses the application and grants necessary permissions to access their calendars.

1.  **Landing:** User navigates to the CalendarSync application URL. They are presented with the hero section describing the value proposition.
2.  **Sign In:** User clicks the "Sign in with Google" button.
3.  **Authentication:** The user is redirected to the Google OAuth consent screen.
4.  **Authorization:**
    *   The application requests access to the user's basic profile and calendar data (`https://www.googleapis.com/auth/calendar`).
    *   Crucially, offline access is requested to obtain a refresh token.
5.  **Callback:** Upon successful authorization, Google redirects back to the `/oauth2callback` endpoint.
6.  **Persistence:** The application stores the user's profile information and refresh token securely in Firestore.
7.  **Dashboard:** The user is redirected to the main dashboard (`/`), which is currently empty as no syncs exist.

## CUJ 2: Creating a Synchronization Job

**Goal:** A user configures a job to merge events from external sources into a specific Google Calendar.

1.  **Initiation:** From the dashboard, the user clicks "+ Create New Sync".
2.  **Configuration Page:** The user is presented with a form (`/create_sync`).
3.  **Select Destination:** The user selects a target Google Calendar from a dropdown populated with calendars they own or have write access to (fetched via Google Calendar API).
4.  **Add Sources:** The user adds one or more sources. For each source, they specify:
    *   **Type:** iCal URL (e.g., from an HR system, university, or Outlook shared link), Google Calendar (selected from their account), or EasyCloud calendar.
    *   **Resource:** The actual URL or ID of the calendar.
    *   **Prefix (Optional):** A string to prepend to imported events (e.g., `[Work]`) to distinguish them visually in the destination calendar.
5.  **Submission:** The user submits the form.
6.  **Validation & Persistence:** The backend validates the inputs (e.g., URL format, limits) and saves the configuration to Firestore in the `syncs` collection.
7.  **Initial Sync:** The backend automatically triggers an immediate background synchronization for the newly created job.
8.  **Completion:** The user is redirected to the dashboard, where the new sync job is listed.

## CUJ 3: Editing a Synchronization Job

**Goal:** A user updates an existing sync job to add/remove sources or change the destination.

1.  **Initiation:** On the dashboard, the user clicks "Edit" next to an existing sync job.
2.  **Form Population:** The `/edit_sync/<id>` page loads, pre-populating the form with the current configuration from Firestore.
3.  **Modification:** The user changes the destination calendar or modifies the list of sources (adding new URLs, changing prefixes, removing items).
4.  **Submission:** The user submits the updated form.
5.  **Persistence:** The backend updates the document in Firestore.
6.  **Auto-Sync:** The backend automatically triggers a sync to reflect the changes immediately.
7.  **Completion:** The user returns to the dashboard with a success message.

## CUJ 4: Manual Synchronization

**Goal:** A user forces an immediate update of their calendar, bypassing the background schedule.

1.  **Initiation:** On the dashboard, the user clicks the "Sync Now" button on a sync card.
2.  **Execution:** A POST request is sent to `/sync/<id>`.
3.  **Rate Limiting:** The backend checks if the job was run recently (e.g., within the last 5 minutes). If so, it rejects the manual request to prevent API quota exhaustion.
4.  **Processing:** If allowed, the backend synchronously executes the `sync_calendar_logic`. It fetches source data, compares it against the destination, and applies inserts/updates.
5.  **Feedback:** Upon completion, the page reloads with a success or failure flash message.

## CUJ 5: Deleting a Synchronization Job

**Goal:** A user stops syncing and removes the configuration.

1.  **Initiation:** (Currently requires navigating to Edit, then deleting, or future UI on dashboard).
2.  **Confirmation:** The user confirms deletion.
3.  **Deletion:** The backend removes the configuration document from Firestore.
    *   *Note: This action only stops future syncs. It does not delete the events that have already been synced into the destination calendar.*

## CUJ 6: Managing EasyCloud Calendars

**Goal:** A user creates a hosted `.ics` file by uploading their own files, to be used as a source or shared externally.

1.  **Creation:** On the dashboard, the user enters a name and clicks "+ Create EasyCloud". A metadata entry is created.
2.  **Uploading Events:**
    *   The user selects a local `.ics` file using the file input on the EasyCloud card.
    *   They select an action: "Add Events" (merge with existing) or "Replace Events" (overwrite).
    *   They click "Upload".
3.  **Processing:** The backend parses the uploaded file, applies the merge strategy, and saves the resulting `.ics` file to Google Cloud Storage.
4.  **Utilization:** The user can now copy the public URL of the EasyCloud calendar or use it as a source in a regular Sync Job.

## Background CUJ: Automated Sync Processing

**Goal:** The system automatically keeps calendars up to date without user intervention.

1.  **Trigger:** Cloud Scheduler fires at a regular interval (e.g., every 30 minutes) and calls the `/tasks/sync_all` endpoint.
2.  **Dispatch:** The dispatcher queries Firestore for all active `syncs`. For each sync document, it enqueues a Cloud Task targeting `/tasks/sync_one` with the `sync_id` in the payload.
3.  **Execution:** The Cloud Task workers execute the `sync_calendar_logic` for each ID.
    *   They fetch fresh data from the sources.
    *   They fetch the current state of the destination calendar.
    *   They compute the differences and execute batched API calls to Google Calendar to apply inserts and updates.
    *   They update the `last_synced_at` timestamp in Firestore.