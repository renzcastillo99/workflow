ROLE: You are an expert app builder who explains things simply to beginners.

GOAL: Build a simple HR system for my small business. I want to keep my employee list in one place, track daily attendance, and handle leave requests. If I already have my records in an Excel file, I want to upload that file and have the system read it and fill in the data for me, so I don't retype everything.

CONTEXT:
- My business: [e.g., a café with 2 branches]
- Who will use it: [e.g., me as owner/HR admin]
- Number of employees: [e.g., 12]
- Work starts at: [e.g., 8:00 AM]. Anyone who times in after this is marked "Late."
- Each employee has: Name, Position, Department or Branch, Contact number, Email, Date hired, Employment status (Probationary, Regular, Contractual, Resigned), Vacation leave balance, Sick leave balance
- Leave types: Vacation, Sick, Emergency. Emergency leave uses the Vacation balance.
- Leave request status: Pending, Approved, Declined
- My existing Excel file (if any) has columns like: [e.g., Name, Position, Branch, Phone, Email, Date Hired, Status]. Column names may not match the system exactly, and the file may also contain columns I don't want imported (like salary or SSS number).

FORMAT:
- One single HTML file I can open in my browser (HTML, CSS, and JavaScript together, no other files)
- An "Employees" tab with an "Add employee" form and a list of all employees, with buttons to edit and delete. Name is required. Ask "Are you sure?" inside the page before deleting.
- An "Attendance" tab with "Time in" and "Time out" buttons for each active employee, and today's board showing who is Present, Late, Absent, or On leave. Each employee can time in only once per day, and can time out only after timing in.
- A "Leave" tab where I can file a leave request (employee, leave type, start date, end date, reason) and approve or decline it. Count leave days from the start date to the end date, including both. Approving a request deducts the days from the employee's balance. A request can only be approved or declined once.
- An "Import" tab (or "Import from Excel" button) with this flow:
  1. File picker that accepts .xlsx and .csv. Also support drag-and-drop.
  2. Let me choose what I'm importing: "Employees" or "Attendance records".
  3. Read the file in the browser only (nothing is uploaded anywhere). If the Excel file has several sheets, let me pick which sheet to read.
  4. Column matching: auto-match my Excel column headers to the system fields (ignore upper/lower case and extra spaces, accept common names such as "Phone" or "Mobile" for Contact number, "Branch" for Department). Show a simple dropdown for each system field so I can fix any wrong match. Columns I don't match are ignored.
  5. Preview: show the first 10 rows as they will be imported, plus a summary such as "12 rows found, 10 ready, 1 duplicate, 1 has errors". List each problem row with a plain-English reason (e.g., "Row 5: Name is missing").
  6. Import rules for employees: Name is required. Detect duplicates (same Email, or same Name if there is no email) and let me choose "Skip duplicates" or "Update existing". Clean up values: trim spaces; turn Excel date numbers and common date formats (e.g., 03/15/2023, 2023-03-15, March 15, 2023) into one standard date; match Employment status ignoring case and default to "Regular" if blank; default leave balances to [e.g., 10 vacation, 5 sick] if blank.
  7. Import rules for attendance: match each row to an employee by name; accept Date, Time in, Time out; mark Late using the work start time above; skip rows whose employee isn't found and list them.
  8. A "Confirm import" button. Nothing is saved until I click it. After importing, show how many were added, updated, and skipped, with an "Undo last import" button.
  9. A "Download Excel template" button that gives me a ready-to-fill CSV file with the correct column headers and 1 sample row.
- A search box and a filter by Department and Employment status
- A summary at the top: total active employees, present today, late today, on leave today, and pending leave requests
- Save the data with localStorage so it stays after I refresh. Wrap every save and load in try/catch so the app still works even if saving is blocked.
- "Export to CSV" buttons for employees, attendance, and leave records
- A "Backup / Restore" option: download all data as one JSON file, and restore it from that file (browser storage can be cleared, so this protects my data)

TONE: Clean, friendly, and easy to read on a phone. Use [your brand colors, e.g., orange and white].

CONSTRAINTS:
- No login, no payroll computation, and no outside services or libraries (no SheetJS or similar). Read .xlsx files with plain JavaScript only: an .xlsx file is a zip of XML files, so open it with the browser's built-in DecompressionStream and DOMParser, and read the sheet data, shared strings, and sheet names. Also support .csv with proper quote handling.
- Old .xls files (Excel 97-2003) are not supported. If I upload one, show a friendly message: "Please open it in Excel and use Save As > Excel Workbook (.xlsx) or CSV."
- Wrap all file reading and parsing in try/catch. A corrupt, empty, or password-protected file must show a friendly message and never break the app.
- Do not store salaries or government ID numbers (SSS, PhilHealth, Pag-IBIG, TIN) in this version. If my Excel file has columns like these, ignore them during import and tell me which columns were skipped for privacy. Do not offer them in the column matching dropdowns.
- Never overwrite or delete existing data during import unless I choose "Update existing" and confirm.
- A leave request cannot use more days than the employee's remaining balance; show a friendly warning instead
- An employee is "On leave" today if they have an approved leave that covers today
- Use my computer's local date and time (Philippine time), not UTC, for anything about "today". Be careful when converting Excel dates so they don't shift by one day.
- Use proper CSV quoting so commas in names or notes don't break the export (and the import)
- Add 6 sample employees with fictional names, plus a few sample attendance records and leave requests, so I can test. Add a "Clear sample data" button so I can start fresh before importing my real file.
- Before you finish, check that every button works and there are no errors. Test the import with a real .xlsx file and a .csv file (including a row with a comma in a name, a missing name, a duplicate, and an Excel date), and tell me the results.
- After building, tell me in 3 short steps how to open and test it, including how to download the file and open it in Chrome to test saving and importing
