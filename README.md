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
```bash
python main.py --config config.yaml
```


## Environments

### Development
- **URL**: https://calendarsync-dev-j3w4ncaxna-uc.a.run.app
- **Project ID**: `calendarsync-napier-dev`
- **Deploy**: Cloud Build triggers on PRs or manual deploy via `cloudbuild-pr-dev.yaml`.

### Production
- **URL**: https://python-cloudrun-app-upgl3iqnkq-uc.a.run.app
- **Project ID**: `calendarsync-napier`
- **Service Name**: `python-cloudrun-app`
- **Deploy**: Cloud Build triggers on push to `main` branch via `cloudbuild.yaml`.

## Local Development (With Google Login)

To run the Flask application locally using the **Development** environment resources:

### 1. Authentication
Authenticate with Google Cloud and set the quota project to the development project:
```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project calendarsync-napier-dev
```

### 2. Configuration
Retrieve the Firebase configuration and secrets from the development environment.

**Option A: From Terraform (Recommended)**
If you have Terraform installed and access to the state:
```bash
cd terraform
terraform workspace select dev
terraform output -json firebase_config
```

**Option B: From Cloud Run**
You can also view the environment variables of the running development service:
```bash
gcloud run services describe calendarsync-dev --project calendarsync-napier-dev --region us-central1 --format="value(spec.template.spec.containers[0].env)"
```

### 3. Run the App
Export the necessary environment variables (replace values with those retrieved above):
```bash
export FIREBASE_API_KEY="..."
export FIREBASE_AUTH_DOMAIN="calendarsync-napier-dev.firebaseapp.com"
export FIREBASE_PROJECT_ID="calendarsync-napier-dev"
export FIREBASE_STORAGE_BUCKET="calendarsync-napier-dev.appspot.com"
export FIREBASE_MESSAGING_SENDER_ID="..."
export FIREBASE_APP_ID="..."
export SECRET_KEY="dev-secret"

python app/app.py
```
Open [http://localhost:8080](http://localhost:8080).

## Contributing
See `docs/contributing.md` for details on how to contribute to this project.
