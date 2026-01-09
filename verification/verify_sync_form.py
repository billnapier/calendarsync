import os
import time
from playwright.sync_api import sync_playwright

def verify_sync_form():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)

        # Read the actual JS file content - relative path from repo root
        with open("app/static/sync_form.js", "r") as f:
            js_content = f.read()

        html_content = f"""
<!DOCTYPE html>
<html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>Test Sync Form</title>
        <style>
            .hidden {{ display: none; }}
            .ical-entry {{ border: 1px solid #ccc; padding: 10px; margin-bottom: 10px; }}
            .btn-danger {{ color: red; }}
        </style>
        <script>
        {js_content}
        </script>
    </head>
    <body>
        <div id="ical-container">
            <div class="ical-entry">
                <input type="hidden" name="source_types" value="ical">
                <input type="hidden" name="source_ids" value="">

                <div class="source-type-group">
                    Type:
                    <select class="source-type-select">
                        <option value="ical">iCal URL</option>
                        <option value="google">Google Cal</option>
                    </select>
                </div>

                <div class="source-input-group">
                    Source:
                    <div class="input-row google-input hidden">
                        <select name="source_ids_visible">
                            <option value="" disabled selected>Select Calendar</option>
                            <option value="cal1">Calendar 1</option>
                            <option value="cal2">Calendar 2</option>
                        </select>
                    </div>
                    <div class="input-row ical-input">
                        <input type="text" name="source_urls" placeholder="URL">
                    </div>
                </div>

                <div class="source-actions">
                     <button type="button" class="btn btn-danger">Remove</button>
                </div>
            </div>
        </div>
        <button type="button" id="add-source-btn">Add Source</button>

        <template id="source-entry-template">
            <div class="ical-entry">
                <input type="hidden" name="source_types" value="ical">
                <input type="hidden" name="source_ids" value="">

                <div class="source-type-group">
                    Type:
                    <select class="source-type-select">
                        <option value="ical">iCal URL</option>
                        <option value="google">Google Cal</option>
                    </select>
                </div>

                <div class="source-input-group">
                    Source:
                    <div class="input-row google-input hidden">
                        <select name="source_ids_visible">
                            <option value="" disabled selected>Select Calendar</option>
                            <option value="cal1">Calendar 1</option>
                            <option value="cal2">Calendar 2</option>
                        </select>
                    </div>
                    <div class="input-row ical-input">
                        <input type="text" name="source_urls" placeholder="URL">
                    </div>
                </div>

                <div class="source-actions">
                    <button type="button" class="btn btn-danger">Remove</button>
                </div>
            </div>
        </template>
    </body>
</html>
        """

        # Ensure dir exists
        os.makedirs("verification", exist_ok=True)

        with open("verification/test_form.html", "w") as f:
            f.write(html_content)

        page = browser.new_page()

        # Capture console logs
        page.on("console", lambda msg: print(f"Console: {msg.text}"))

        # Absolute path for goto
        cwd = os.getcwd()
        page.goto(f"file://{cwd}/verification/test_form.html")

        # Verify initial state
        time.sleep(0.5)

        # Check if first remove button is hidden
        remove_btns = page.locator(".btn-danger")
        first_btn = remove_btns.nth(0)

        if first_btn.is_visible():
            print("Error: First remove button should be hidden (display: none)")
            display = first_btn.evaluate("el => getComputedStyle(el).display")
            print(f"First button display: {display}")
        else:
            print("Success: First remove button is hidden")

        # Test Adding
        print("Clicking Add Source...")
        page.click("#add-source-btn")

        entries = page.locator(".ical-entry")
        print(f"Entries count: {entries.count()}")
        if entries.count() != 2:
            print("Error: Should have 2 entries")
        else:
             print("Success: Added entry")

        # Both remove buttons should be visible
        if not remove_btns.nth(0).is_visible():
            print("Error: First remove button should be visible now")
        if not remove_btns.nth(1).is_visible():
            print("Error: Second remove button should be visible now")

        # Test Type Switching
        print("Switching type to Google...")
        selects = page.locator(".source-type-group select")
        selects.nth(1).select_option("google")

        # Check visibility
        entry2 = entries.nth(1)
        google_input = entry2.locator(".google-input")

        time.sleep(0.2)

        is_google_visible = google_input.evaluate("el => !el.classList.contains('hidden')")
        print(f"Google input visible: {is_google_visible}")

        if not is_google_visible:
             print("Error: Google input should be visible")
        else:
            print("Success: Google input is visible")

        # Test Removing
        print("Removing first entry...")
        remove_btns.nth(0).click()

        if entries.count() != 1:
            print("Error: Should have 1 entry left")
        else:
             print("Success: Removed entry")

        page.screenshot(path="verification/verification.png")
        browser.close()

if __name__ == "__main__":
    verify_sync_form()
