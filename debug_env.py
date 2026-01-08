import sys
import os

print(f"Python executable: {sys.executable}")
print(f"CWD: {os.getcwd()}")
print("Sys Path:")
for p in sys.path:
    print(p)

try:
    import icalendar

    print(f"icalendar imported from: {icalendar.__file__}")
except ImportError as e:
    print(f"Failed to import icalendar: {e}")

try:
    import app.app

    print(f"app.app imported successfully")
except Exception as e:
    print(f"Failed to import app.app: {e}")
