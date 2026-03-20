import firebase_admin
from firebase_admin import credentials
from firebase_admin import firestore
import os

import sys

# Initialize Firebase app
# We use ADC (Application Default Credentials)
if not firebase_admin._apps:
    project_id = sys.argv[1] if len(sys.argv) > 1 else "calendarsync-napier-dev"
    print(f"Initializing for project: {project_id}")
    cred = credentials.ApplicationDefault()
    firebase_admin.initialize_app(
        cred,
        {
            "projectId": project_id,
        },
    )

db = firestore.client()

print("Listing syncs collection...")
try:
    syncs = db.collection("syncs").stream()
    count = 0
    for doc in syncs:
        print(f"Sync ID: {doc.id}, Data: {doc.to_dict()}")
        count += 1
    print(f"Total syncs found: {count}")
except Exception as e:
    print(f"Error fetching syncs: {e}")
