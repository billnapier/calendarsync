# CalendarSync

## Description
CalendarSync is a powerful tool designed to synchronize and coalesce multiple iCal calendar feeds into a single, unified iCal calendar. It helps you manage disjointed schedules by aggregating events from various sources—such as work, personal, and shared calendars—into one seamless feed.

## Features
- **Multi-Source Aggregation**: ingest events from multiple `.ics` URLs or local files and combine them.
- **Unified Output**: Exposes a single `.ics` feed that can be subscribed to by any standard calendar client (Google Calendar, Apple Calendar, Outlook, etc.).
- **Filtering & Deduplication** (Planned): Rules to filter specific events or merge duplicate entries.
- **Privacy Controls** (Planned): Options to mask sensitive event details in the output feed.

## Getting Started

### Prerequisites
- Python 3.8+
- `pip`

### Installation
1. Clone the repository:
   ```bash
   git clone https://github.com/billnapier/calendarsync
   cd calendarsync
   ```
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

### Configuration
Create a `config.yaml` file to define your sources:

```yaml
sources:
  - name: "Work Calendar"
    url: "https://example.com/calendar/work.ics"
  - name: "Personal Calendar"
    url: "https://calendar.google.com/calendar/ical/.../basic.ics"

output:
  file: "unified_calendar.ics"
```

### Usage
python main.py --config config.yaml
```

## Local Development (With Google Login)

To run the Flask application locally with Google Login support:

### 1. Enable Firebase
1. Go to the [Firebase Console](https://console.firebase.google.com/).
2. Click **Add project** and select your existing Google Cloud project (e.g., `calendarsync-napier`).
3. Inside the project, add a **Web App** (click `</>`) to get your `firebaseConfig`.

### 2. Enable Google Sign-In
1. In Firebase Console -> Authentication -> Sign-in method.
2. Enable the **Google** provider.

### 3. Application Credentials
Run the following to allow your local credentials to access the Auth APIs:
```bash
gcloud auth application-default set-quota-project <YOUR_PROJECT_ID>
```

### 4. Run the App
Set the Firebase config environment variables (retrieve values from Terraform output `terraform output -json firebase_config` or Firebase Console):
```bash
export FIREBASE_API_KEY="AIza..."
export FIREBASE_AUTH_DOMAIN="<project>.firebaseapp.com"
export FIREBASE_PROJECT_ID="<project-id>"
export FIREBASE_STORAGE_BUCKET="<project>.appspot.com"
export FIREBASE_MESSAGING_SENDER_ID="1234..."
export FIREBASE_APP_ID="1:..."
export SECRET_KEY="dev-secret"

python app/app.py
```
Open [http://localhost:8080](http://localhost:8080).

## Contributing
See `docs/contributing.md` for details on how to contribute to this project.
