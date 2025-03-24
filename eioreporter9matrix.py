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
import pickle
import json
import re
import schedule
import time
from datetime import datetime, timedelta
from nio import AsyncClient, RoomMessageText, EncryptionError, LocalProtocolError

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

# Matrix configuration
MATRIX_HOMESERVER = "https://my.chat.server"  			# Replace with your homeserver
MATRIX_USER = "@mybot:my.chat.server"          			# Replace with your bot’s user ID
MATRIX_PASSWORD = "mybotspassword!"          				# Replace with your bot’s password
MATRIX_ROOM_ID = "!reportroomid:my.chat.server"  		# Replace with your room ID for tasks due
MATRIX_SUMMARY_ROOM_ID = "!summaryroomid:my.chat.server"	# Replace with your room ID for maintenance summary
STORE_PATH = "./matrix_store"                  				# Directory for encryption keys
SESSION_FILE = "./matrix_session.pkl"          				# File to store session data

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

# Generate maintenance report
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

    # Prepare the Matrix message content
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

# Load or save session data
def load_session():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, "rb") as f:
            return pickle.load(f)
    return None

def save_session(client):
    session_data = {
        "device_id": client.device_id,
        "access_token": client.access_token
    }
    with open(SESSION_FILE, "wb") as f:
        pickle.dump(session_data, f)

# Matrix interaction
async def message_callback(room, event, client):
    print(f"Callback triggered for room: {room.room_id}")
    if isinstance(event, RoomMessageText):
        print(f"Message event received: {event.body} from {event.sender}")
        if event.sender != MATRIX_USER:
            print(f"Processing message from {event.sender}: {event.body}")
            await process_maintenance_response(client, event.sender, event.body)
    else:
        print(f"Ignored non-text event: {event}")

# Handeling user repsonse
async def process_maintenance_response(client, sender, message):
    pattern = r"(.+?)\s+on\s+(.+?)\s+completed"
    match = re.match(pattern, message.lower().strip())
    if match:
        task, machine = match.groups()
        # Validate task and machine
        task_title = " ".join(word.capitalize() for word in task.split())	# Fix: Capitalize each word
        machine_input = " ".join(word.capitalize() for word in machine.split())
        machine_title = None
        for key in maintenance_tasks.keys():
            if key.lower() == machine_input.lower():	# Case-insensitive match
                machine_title = key	# Use the exact key from maintenance_tasks
                break
        if not machine_title:
            await client.room_send(
                room_id=MATRIX_ROOM_ID,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"Invalid machine: {machine}"}
            )
            return
        if task_title not in maintenance_tasks[machine_title]:
            await client.room_send(
                room_id=MATRIX_ROOM_ID,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"Invalid task: {task} for {machine}"}
            )
            return
        # Find the task in maintenance_due
        task_info = next((t for t in maintenance_due.get(machine_title, []) if t["task"] == task_title), None)
        if not task_info:
            await client.room_send(
                room_id=MATRIX_ROOM_ID,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": f"{task} on {machine} is not currently due"}
            )
            return
        runtime_when_due = task_info["runtime_when_due"]
        print(f"Parsed: {task} on {machine} completed by {sender}")
        await store_maintenance_action(client, sender, task_title, machine_title, runtime_when_due)
    else:
        await client.room_send(
            room_id=MATRIX_ROOM_ID,
            message_type="m.room.message",
            content={"msgtype": "m.text", "body": "Invalid format. Use: '[task] on [machine] completed'"}
        )

# Save maintenance action - Fetch current runtime on completion
async def store_maintenance_action(client, user, task, machine, runtime_when_due):
    # Fetch current runtime at completion
    machine_runtimes = await fetch_runtimes()
    current_runtime = machine_runtimes.get(machine, "unknown")
    action = {
        "user": user,
        "task": task.lower(),
        "machine": machine.lower(),
        "timestamp": datetime.now().isoformat(),
        "runtime_when_due": runtime_when_due,
        "runtime_at_completion": current_runtime
    }
    log = load_maintenance_log()
    log.append(action)
    with open("maintenance_log.json", "w") as f:
        json.dump(log, f, indent=4)
    print(f"Stored maintenance action: {action}")
    # Send feedback
    feedback = f"{task.capitalize()} on {machine.capitalize()} logged by {user} at {current_runtime} hours (due at {runtime_when_due} hours)"
    await client.room_send(
        room_id=MATRIX_ROOM_ID,
        message_type="m.room.message",
        content={"msgtype": "m.text", "body": feedback}
    )

# Async function to send encrypted message
async def send_matrix_message(client, room_id, message_type="due"):
    if message_type == "due":
        message_body, global_maintenance_due = await generate_report()
        global maintenance_due
        maintenance_due = global_maintenance_due	# Update global for response validation
    elif message_type == "summary":
        message_body = await generate_summary_report(maintenance_due)

    try:
        print(f"Sending encrypted message to: {room_id}")
        send_response = await asyncio.wait_for(
            client.room_send(
                room_id=room_id,
                message_type="m.room.message",
                content={"msgtype": "m.text", "body": message_body}
            ),
            timeout=10
        )
        print("Message sent! Response:", send_response)
    except Exception as e:
        print(f"Failed to send report to {room_id}: {e}")

# Main function
async def main():
    if not os.path.exists(STORE_PATH):
        os.makedirs(STORE_PATH)

    client = AsyncClient(MATRIX_HOMESERVER, MATRIX_USER, store_path=STORE_PATH)

    # Save PID for background control
    with open("bot.pid", "w") as f:
        f.write(str(os.getpid()))

    # Initialize Matrix session
    session = load_session()
    if session:
        client.device_id = session["device_id"]
        client.access_token = session["access_token"]
        print(f"Reusing session with device ID: {client.device_id}")
    else:
        print("No session found, creating new one...")

    try:
        print(f"Connecting to {MATRIX_HOMESERVER}...")
        if not session:
            login_response = await asyncio.wait_for(client.login(MATRIX_PASSWORD), timeout=5)
            print("Logged in! Response:", login_response)
            save_session(client)
        else:
            client.restore_login(MATRIX_USER, device_id=client.device_id, access_token=client.access_token)
            print("Session restored!")

        print("Syncing with full state...")
        await asyncio.wait_for(client.sync(timeout=5000, full_state=True), timeout=10)
        print("Sync complete!")
        for room_id in [MATRIX_ROOM_ID, MATRIX_SUMMARY_ROOM_ID]:
            if room_id not in client.rooms:
                print(f"Room {room_id} not found! Joining...")
                await client.join(room_id)
                await asyncio.wait_for(client.sync(timeout=5000), timeout=10)
        print(f"Room {MATRIX_ROOM_ID} encrypted: {client.rooms[MATRIX_ROOM_ID].encrypted}")
        print(f"Room {MATRIX_SUMMARY_ROOM_ID} encrypted: {client.rooms[MATRIX_SUMMARY_ROOM_ID].encrypted}")

        print("Fetching and trusting all devices...")
        try:
            await client.keys_upload()
            print("Keys uploaded!")
        except LocalProtocolError as e:
            print(f"Key upload skipped: {e}")

        print("Querying device keys...")
        await client.keys_query()
        devices_list = []
        for user_devices in client.device_store.values():
            for device in user_devices.values():
                devices_list.append((device.user_id, device.device_id))
        print("Keys queried! Devices in store:", devices_list)

        # Trust all devices
        for user_devices in client.device_store.values():
            for device in user_devices.values():
                print(f"Trusting {device.device_id} for {device.user_id}")
                client.verify_device(device)

        print("Syncing after key operations...")
        await asyncio.wait_for(client.sync(timeout=5000), timeout=10)
        print("Sync complete after keys!")

        # Schedule due tasks reports Monday-Friday at 2:15 PM
        for day in ["monday", "tuesday", "wednesday", "thursday", "friday"]:
            getattr(schedule.every(), day).at("14:15").do(
                lambda: asyncio.create_task(send_matrix_message(client, MATRIX_ROOM_ID, "due"))
            )
            # Schedule summary report Monday-Friday at 2:17 PM
            getattr(schedule.every(), day).at("14:17").do(
                lambda: asyncio.create_task(send_matrix_message(client, MATRIX_SUMMARY_ROOM_ID, "summary"))
            )

        # Send initial due report to verify setup
        await send_matrix_message(client, MATRIX_ROOM_ID, "due")
        # Send initial summary report
        await send_matrix_message(client, MATRIX_SUMMARY_ROOM_ID, "summary")

        # Continuous loop for scheduling and syncing
        print("Starting main loop for scheduling and syncing...")
        client.add_event_callback(
            lambda room, event: message_callback(room, event, client),
            RoomMessageText
        )
        while True:
            schedule.run_pending()
            await client.sync(timeout=30000)	# Sync every 30 seconds to process messages
            await asyncio.sleep(1)	# Small sleep to prevent tight loop

    except asyncio.TimeoutError:
        print("Operation timed out—check network, server, or credentials.")
    except EncryptionError as e:
        print(f"Encryption error: {e}")
    except Exception as e:
        print(f"Main failed: {e}")
        import traceback
        traceback.print_exc()
    finally:
        print("Closing client...")
        await client.close()

if __name__ == "__main__":
    asyncio.run(main())
