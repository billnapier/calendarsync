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
Run the sync script:
```bash
python main.py --config config.yaml
```

## Contributing
See `docs/contributing.md` for details on how to contribute to this project.
