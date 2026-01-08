## 2024-05-24 - Focus Management on Dynamic Inputs
**Learning:** When dynamically adding or toggling form inputs (like "Add another source" or switching "Source Type"), users expect the focus to move to the new interactive element immediately. This reduces friction for keyboard users and power users who want to keep typing without reaching for the mouse.
**Action:** Always programmatically `focus()` the relevant input field after appending it to the DOM or unhiding it. This simple change significantly improves the "flow" of form completion.
