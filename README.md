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
- **Deploy**: GitHub Actions runs Terraform Plan on Pull Requests to `main`.

### Production
- **URL**: https://python-cloudrun-app-upgl3iqnkq-uc.a.run.app
- **Project ID**: `calendarsync-napier`
- **Service Name**: `python-cloudrun-app`
- **Deploy**: GitHub Actions triggers on push to `main` branch. Deploys application and applies Terraform changes.

## Local Development (With Google OAuth)

To run the Flask application locally using the **Development** environment resources:

### 1. Prerequisites
- **OAuth Credentials**: Ensure you have created an OAuth Client ID and Secret in the Google Cloud Console for the `calendarsync-napier-dev` project.
- **Secrets**: Ensure `google_client_id` and `google_client_secret` are created in Google Secret Manager in the `calendarsync-napier-dev` project.
- **Permissions**: Your user account must have `Secret Manager Secret Accessor` role on the project.

### 2. Authentication
Authenticate with Google Cloud and set the quota project:
```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project calendarsync-napier-dev
```

### 3. Run the App
Setup the environment and run the application:
```bash
# Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r app/requirements.txt

# Set Environment Variables
export GOOGLE_CLOUD_PROJECT=calendarsync-napier-dev
export FLASK_ENV=development

# Run the application
python app/app.py
```
Open [http://localhost:8080](http://localhost:8080).
Open [http://localhost:8080](http://localhost:8080).

## Terraform

To manage infrastructure via Terraform locally:

1. Navigate to the `terraform` directory:
   ```bash
   cd terraform
   ```

### Development
```bash
terraform workspace select dev
terraform plan -var-file=dev.tfvars
```

### Production
```bash
terraform workspace select prod
terraform plan -var-file=terraform.tfvars
```


## Contributing
See `docs/contributing.md` for details on how to contribute to this project.
