#################################################################################################
# DISCLAIMER:                                                                                   #
# This software is provided "as is", without warranty of any kind, express or implied,          #
# including but not limited to the warranties of merchantability, fitness for a particular      #
# purpose, and noninfringement. In no event shall Linor Technology (Linortek) or the author be  #
# liable for any claim, damages (including, without limitation, damages to hardware,            #
# software, or data), or other liability, whether in an action of contract, tort, or            #
# otherwise, arising from, out of, or in connection with the software or the use or             #
# other dealings in the software. Linor Technology (Linortek) does not provide support for this #
# code. Use at your own risk.                                                                   #
#                                                                                               #
# Copyright (C) 2025 Linor Technology                                                           #
#                                                                                               #
# This program is free software: you can redistribute it and/or modify                          #
# it under the terms of the GNU General Public License as published by                          #
# the Free Software Foundation, either version 3 of the License, or                             #
# (at your option) any later version.                                                           #
#                                                                                               #
# This program is distributed in the hope that it will be useful,                               #
# but WITHOUT ANY WARRANTY; without even the implied warranty of                                #
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the                                 #
# GNU General Public License for more details.                                                  #
#                                                                                               #
# You should have received a copy of the GNU General Public License                             #
# along with this program.  If not, see <https://www.gnu.org/licenses/>.                        #
#                                                                                               #
#################################################################################################

import requests
import xml.etree.ElementTree as ET
import asyncio
import os
import json
import re
import schedule
import time
from datetime import datetime, timedelta
import smtplib
import imaplib
import email
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Config and data
devices = [
    {
	"url": "http://172.16.4.99/hours.xml",
	"machines": ("Compressor", "CNC Machine")	# Device 1's machines (machine1,machine2), name machines whatever you want
    },
    {
	"url": "http://172.16.4.102/hours.xml",
	"machines": ("Motor", "Lathe")		# Device 2's machines
    },
    # Add more device URLs here as needed following above format
]

# NOTE: If a device only reports one machine, adjust the machines tuple and skip the second assignment:
#devices = [
       #"url": "http://192.168.1.103/hours.xml",
       # "machines": ("Heater",),
#]
# In the loop:
	# machine1_name = device["machines"][0]
	#machine_runtimes[machine1_name] = hours_list[0]  # Only assign first value
# /NOTE

# Define maintenance tasks with their intervals (in hours)

maintenance_tasks = {
    "Compressor": {
	"Drain Water": 40,
	"Check Desiccant": 100,
	"Belt Inspection": 200
    },
    "CNC Machine": {
	"Lubricate": 50
    },
    "Motor": {
	"Oil Change": 40,
	"Belt Inspection": 200
    },
    "Lathe": {
	"Lubricate": 100
    }
}

# Email configuration
# NOTE: if using gmail you will need an 'app password'.
# Go to your Google account settings > Security > 2-Step Verification
# Set-up 2-step verification if not already setup (this is required to use app passwords)
# Click the arrow next to 'app passwords' on 2step verification page and create an app password
# Other email providers may or may not require something similar /NOTE

EMAIL_SENDER = "email@gmail.com"  		# Replace with your email
EMAIL_PASSWORD = "emailpassword"     	# Replace with your email password or app-specific password (see note above)
SMTP_SERVER = "smtp.gmail.com"           	# Replace with your SMTP server (e.g., smtp.gmail.com for Gmail)
SMTP_PORT = 587                          	# Replace with your SMTP port (usually 587)
IMAP_SERVER = "imap.gmail.com"			# Replace with your IMAP server (e.g., imap.gmail.com)
IMAP_PORT = 993					# Replace with your IMAP port (usually 993)
# Consider storing EMAIL_PASSWORD securely (e.g., in an environment variable or config file) rather than hardcoding it.

# Recipients for due tasks report
DUE_RECIPIENTS = ["user1@gmail.com", "user2#gmail.com"]	# To
DUE_CC = ["user3@gmail.com", "user4@gmail.com"]               # CC
DUE_BCC = ["user5@gmail.com", "user6@gmail.com"]                	# BCC

# Recipients for summary report
SUMMARY_RECIPIENTS = ["user1@gmail.com"]		# To
SUMMARY_CC = ["user2@gmail.com"]                   # CC
SUMMARY_BCC = ["user3@gmail.com"]                     # BCC

# Fetch runtime - Made into a function for scheduling
async def fetch_runtimes():
    machine_runtimes = {}
    for device in devices:
        url = device["url"]
        machine1_name, machine2_name = device["machines"]
        try:
            response = requests.get(url)
            xml_data = response.text
            root = ET.fromstring(xml_data)
            hours_string = root.find(".//hours").text
            hours_list = hours_string.split("|")
            machine_runtimes[machine1_name] = float(hours_list[0])
            machine_runtimes[machine2_name] = float(hours_list[3])
        except Exception as e:
            print(f"Error fetching data from {url}: {e}")
    return machine_runtimes

# Load maintenance log
def load_maintenance_log():
    try:
        with open("maintenance_log.json", "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return []

# Save maintenance log
def save_maintenance_log(log):
    with open("maintenance_log.json", "w") as f:
        json.dump(log, f, indent=4)

# Generate maintenance report with reply instructions
async def generate_report():
    machine_runtimes = await fetch_runtimes()
    maintenance_log = load_maintenance_log()
    maintenance_due = {machine: [] for device in devices for machine in device["machines"] }

    for machine_name in machine_runtimes:
        due_tasks = []
        current_runtime = machine_runtimes[machine_name]
        for task, interval in maintenance_tasks[machine_name].items():
            last_done_entries = [
                entry for entry in maintenance_log
                if entry["machine"].lower() == machine_name.lower() and entry["task"].lower() == task.lower()
            ]
            last_done = max((entry["timestamp"] for entry in last_done_entries), default=None) if last_done_entries else None
            last_runtime = max((entry.get("runtime_at_completion", 0) for entry in last_done_entries), default=0) if last_done_entries else 0

            if last_done:
                last_time = datetime.fromisoformat(last_done)
                hours_since = (datetime.now() - last_time).total_seconds() / 3600
                if hours_since < interval:
                    continue	# Task not due yet

            # Calculate the first runtime when the task became due after last completion
            if current_runtime >= last_runtime + interval:
                runtime_when_due = last_runtime + interval
                # Adjust runtime_when_due to the most recent due point before or at current runtime
                overdue_intervals = ((current_runtime - last_runtime) // interval) * interval
                runtime_when_due = last_runtime + overdue_intervals if overdue_intervals > 0 else runtime_when_due
                due_tasks.append({"task": task, "runtime_when_due": runtime_when_due})
        maintenance_due[machine_name] = due_tasks

    # Prepare the email content
    message_body = "Automated Maintenance Report\n\n"
    for machine_name in maintenance_due:
        runtime = machine_runtimes.get(machine_name, "Data unavailable")
        message_body += f"{machine_name} runtime: {runtime} hours\n"
        if maintenance_due[machine_name]:
            message_body += "  Maintenance due:\n"
            for task_info in maintenance_due[machine_name]:
                task = task_info["task"]
                runtime_when_due = task_info["runtime_when_due"]
                message_body += f"    - {task} (due at {runtime_when_due} hours)\n"
        else:
            message_body += "  No maintenance due yet.\n"
        message_body += "\n"

    # Add reply instructions
    message_body += "To log completed tasks, reply to this email with:\n"
    message_body += "  '[task] on [machine] completed'\n"
    message_body += "For multiple tasks, use one per line, e.g.:\n"
    message_body += "  Lubricate on CNC Machine completed\n"
    message_body += "  Oil Change on Motor completed\n"
    message_body += "Tasks must match the due tasks listed above.\n"

    return message_body, maintenance_due

# Generate summary report (completed and pending tasks)
async def generate_summary_report(maintenance_due):
    maintenance_log = load_maintenance_log()
    now = datetime.now()
    yesterday = now - timedelta(days=1)

    # Completed tasks in the last 24 hours
    completed_tasks = [
        entry for entry in maintenance_log
        if datetime.fromisoformat(entry["timestamp"]) >= yesterday
    ]

    message_body = "Daily Maintenance Summary Report\n\n"

    # Completed tasks section
    message_body += "Tasks Completed in Last 24 Hours:\n"
    if completed_tasks:
        for entry in completed_tasks:
            machine = entry["machine"].capitalize()
            task = entry ["task"].capitalize()
            runtime_at_completion = entry["runtime_at_completion"]
            timestamp = entry["timestamp"]
            user = entry["user"]
            message_body += f"  - {task} on {machine} by {user} at {runtime_at_completion} hours (completed {timestamp})\n"
    else:
        message_body += "  - None\n"
    message_body += "\n"

    # Pending tasks section
    message_body += "Pending Maintenance Tasks:\n"
    pending_found = False
    for machine_name, tasks in maintenance_due.items():
        if tasks:
            pending_found = True
            message_body += f"  {machine_name}:\n"
            for task_info in tasks:
                task = task_info["task"]
                runtime_when_due = task_info["runtime_when_due"]
                message_body += f"    - {task} (due at {runtime_when_due} hours)\n"
    if not pending_found:
        message_body += "  - None\n"

    return message_body

# Send email function
def send_email(subject, body, recipients, cc=None, bcc=None):
    msg = MIMEMultipart()
    msg["From"] = EMAIL_SENDER
    msg["To"] = ", ".join(recipients) if isinstance(recipients, list) else recipients
    msg["Subject"] = subject

    # Prepare full recipient list for SMTP envelope
    all_recipients = recipients.copy() if isinstance(recipients, list) else [recipients]
    if cc:
        msg["Cc"] = ", ".join(cc) if isinstance(cc, list) else cc
        all_recipients.extend(cc if isinstance(cc, list) else [cc])
    if bcc:
        all_recipients.extend(bcc if isinstance (bcc, list) else [cbb])

    print(f"Prepared recipients: {all_recipients}")

    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()  # Enable TLS
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, all_recipients,msg.as_string())
            print(f"Email sent successfully to {msg['To']}")
            if cc:
                print(f"CC: {msg['Cc']}")
            if bcc:
                print(f"BCC: {' '.join(bcc) if isinstance(bcc, list) else bcc}")
    except Exception as e:
        print(f"Failed to send email: {e}")

# Process email responses with debugging
async def process_email_responses(maintenance_due):
    print("Checking for email responses...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        print("Connecting to IMAP server...")
        mail.login(EMAIL_SENDER, EMAIL_PASSWORD)
        print("Logged in to IMAP server.")
        mail.select("inbox")
        print("Selected inbox.")

        search_query = 'SUBJECT "Automated Maintenance Report"'
        print(f"Searching with query: {search_query}")
        status, messages = mail.search(None, search_query)
        print(f"Search status: {status}, message IDs: {messages[0].split()}")

        if status != "OK" or not messages[0]:
            print("No matching emails found.")
            mail.logout()
            return

        message_ids = messages[0].split()
        for msg_id in message_ids:
            print(f"Fetching email ID: {msg_id}")
            status, msg_data = mail.fetch(msg_id, "(RFC822)")
            if status != "OK":
                print(f"Failed to fetch email ID {msg_id}")
                continue

            raw_email = msg_data[0][1]
            email_msg = email.message_from_bytes(raw_email)
            sender = email_msg.get("Reply-To", email_msg["From"])
            subject = email_msg.get("Subject", "")
            print(f"Processing email from {sender} with subject: {subject}")

            if "Re: Automated Maintenance Report" not in subject:
                print("Not a reply to Automated Maintenance Report, skipping.")
                continue

            body = ""
            if email_msg.is_multipart():
                for part in email_msg.walk():
                    if part.get_content_type() == "text/plain":
                        charset = part.get_content_charset() or "utf-8"
                        body = part.get_payload(decode=True).decode(charset, errors="replace")
                        break
            else:
                charset = email_msg.get_content_charset() or "utf-8"
                body = email_msg.get_payload(decode=True).decode(charset, errors="replace")
            print(f"Email body: {body}")

            # Initialize lists for confirmation
            tasks = []
            invalid_tasks = []
            accepted_tasks = []
            rejected_tasks = []

# Parse only new content, stop at signature or thread
            pattern = r"(.+?)\s+on\s+(.+?)\s+completed"
            lines = body.split("\n")
            for line in lines:
                line = line.strip()
                if line.startswith("--") or line.startswith("___") or line.startswith("Thank you"):  # Common signature delimiters
                    break
                if line.startswith(">") or not line:  # Skip quoted text or empty lines
                    continue
                match = re.match(pattern, line)
                if match:
                    task, machine = match.groups()
                    tasks.append((task.strip(), machine.strip()))
                elif line:
                    invalid_tasks.append(line)

            print(f"Parsed tasks: {tasks}")
            print(f"Invalid lines: {invalid_tasks}")

            if not tasks and not invalid_tasks:
                print(f"No tasks or invalid lines found in reply from {sender}")
                confirmation_body = "Maintenance Task Submission Result:\n\nNo tasks submitted in your reply."
                send_email(
                    subject="Maintenance Task Confirmation",
                    body=confirmation_body,
                    recipients=[sender]
                )
                mail.store(msg_id, "+FLAGS", "\\Deleted")
                continue

            machine_runtimes = await fetch_runtimes()
            log = load_maintenance_log()

            for task, machine in tasks:
                task_title = " ".join(word.capitalize() for word in task.split())
                machine_input = " ".join(word.capitalize() for word in machine.split())
                machine_title = next((key for key in maintenance_tasks if key.lower() == machine_input.lower()), None)

                if not machine_title:
                    rejected_tasks.append(f"{task} on {machine} - Invalid machine")
                    continue
                if task_title not in maintenance_tasks[machine_title]:
                    rejected_tasks.append(f"{task} on {machine} - Invalid task")
                    continue

                task_info = next((t for t in maintenance_due.get(machine_title, []) if t["task"] == task_title), None)
                if not task_info:
                    rejected_tasks.append(f"{task} on {machine} - Not currently due")
                    continue

                runtime_when_due = task_info["runtime_when_due"]
                current_runtime = machine_runtimes.get(machine_title, "unknown")
                action = {
                    "user": sender,
                    "task": task_title.lower(),
                    "machine": machine_title.lower(),
                    "timestamp": datetime.now().isoformat(),
                    "runtime_when_due": runtime_when_due,
                    "runtime_at_completion": current_runtime
                }
                log.append(action)
                accepted_tasks.append(f"{task_title} on {machine_title}")
                print(f"Logged: {task_title} on {machine_title} completed by {sender}")

            save_maintenance_log(log)

            # Send confirmation email
            confirmation_body = "Maintenance Task Submission Result:\n\n"
            if accepted_tasks:
                confirmation_body += "Accepted Tasks:\n"
                for task in accepted_tasks:
                    confirmation_body += f"  - {task}\n"
            else:
                confirmation_body += "No tasks accepted.\n"
            if rejected_tasks or invalid_tasks:
                confirmation_body += "\nRejected Tasks:\n"
                for task in rejected_tasks:
                    confirmation_body += f"  - {task}\n"
                for task in invalid_tasks:
                    confirmation_body += f"  - {task} - Invalid format (use '[task] on [machine] completed')\n"
            send_email(
                subject="Maintenance Task Confirmation",
                body=confirmation_body,
                recipients=[sender]
            )

            mail.store(msg_id, "+FLAGS", "\\Deleted")
            print(f"Marked email ID {msg_id} as deleted.")

        mail.expunge()
        print("Expunged deleted emails.")
        mail.logout()
        print("Logged out of IMAP server.")
    except Exception as e:
        print(f"Failed to process email responses: {e}")

# Async function to send reports via email
async def send_report(report_type="due"):
    if report_type == "due":
        message_body, global_maintenance_due = await generate_report()
        global maintenance_due
        maintenance_due = global_maintenance_due
        subject = "Automated Maintenance Report"
        recipients = DUE_RECIPIENTS
        cc = DUE_CC
        bcc = DUE_BCC
    elif report_type == "summary":
        message_body = await generate_summary_report(maintenance_due)
        subject = "Daily Maintenance Summary Report"
        recipients = SUMMARY_RECIPIENTS
        cc = SUMMARY_CC
        bcc = SUMMARY_BCC

    send_email(subject, message_body, recipients, cc, bcc)

# Main function with debug
async def main():

    # Save PID for background control
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))

    try:
        # Schedule due tasks reports Monday-Friday at 2:15 PM
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
            getattr(schedule.every(), day).at("14:15").do(
                lambda: asyncio.create_task(send_matrix_message(client, MATRIX_ROOM_ID, "due"))
            )
            # Schedule summary report Monday-Friday at 2:17 PM
            getattr(schedule.every(), day).at("14:17").do(
                lambda: asyncio.create_task(send_matrix_message(client, MATRIX_SUMMARY_ROOM_ID, "summary"))
            )

        # Schedule email response checking every 5 minutes
        schedule.every(5).minutes.do(
            lambda: asyncio.create_task(process_email_responses(maintenance_due))
        )

        # Send initial due report to verify setup
        await send_report("due")
        # Send initial summary report
        await send_report("summary")

        # Continuous loop for scheduling
        print("Starting main loop for scheduling...")
        last_status_print = 0
        while True:
            current_time = time.time()
            if current_time - last_status_print >= 60:
                print("Running scheduled tasks...")
                last_status_print = current_time
            schedule.run_pending()
            await asyncio.sleep(1)	# Small sleep to prevent tight loop

    except Exception as e:
        print(f"Main failed: {e}")
        import traceback
        traceback.print_exc()

def test_imap_connection():
    print("Testing IMAP connection...")
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        mail.login(EMAIL_SENDER, EMAIL_PASSWORD)
        mail.select("inbox")
        status, messages = mail.search(None, f'(FROM "{EMAIL_SENDER}" SUBJECT "Automated Maintenance Report")')
        print(f"IMAP test - Search status: {status}, Messages: {messages[0].split()}")
        mail.logout()
    except Exception as e:
        print(f"IMAP test failed: {e}")

if __name__ == "__main__":
#    test_imap_connection()  # Run this separately to test IMAP
    asyncio.run(main())
