# eIO-reporter

This is not intended to be a turn-key solution. This is meant to be a starting point to help automate reporting and logging of maintenance tasks using the Linortek NHM, Ultra 300, or eIO hourmeters.

This program creates a bot that fetches runtimes gathered by your Linortek devices, compares it to a list of maintenance tasks and their intervals, and listens to a response stating that the task has been completed. Upon receiving this response, the bot will either confirm that the task has been marked complete and then log it into a .json file, or notify the user of incorrect spelling or syntax and prompt them to resubmit.

This bot will send a report and a summary consisting or completed tasks with the past 24 hours once per day.

Included here are 2 versions of this bot. One uses email (you'll probably be more likely to use this) the other integrates with a Matrix chat server. I commented the code as best I could, everything should be pretty self-explanatory. When in doubt follow the example.

# To Configure:

1) make sure you have the required packages

2) provide the url or IP address of your Linortek devices followed by /hours.xml
3) enter the names you prefer for the machines they are monitoring
4) under "maintenance_tasks" for each machine add your periodic maintenance items followed by the runtime interval in hours

# Email version:
Edit the following:
* EMAIL_SENDER - the account you wish to use to send the report email from
* EMAIL_PASSWORD - password or app password (see the note in the program) for the above account. Consider modifying the code to use an environment variable or config file rather than hardcoding to be more secure
* SMTP_SERVER
* SMTP_PORT
* IMAP_SERVER - to read the response
* IMAP_PORT

* enter your recipients, CC's, and BCC's

* if you use a signature in your email you may wish to edit line 338 so the bot ignores the signature or you can manually delete the signature from the response

* Line 458: add the time of day you want to send the report
* Line 461: add the time of day you want to send the summary

Upon receiving the report, you can reply with [task] on [machine] completed (for multiple tasks, use a new line). By default the bot checks the email every 5 minutes, you can change this on line 467 (schedule.every(x).minutes)

# Matrix version
Edit the following:
* MATRIX_HOMESERVER - your homeserver url
* MATRIX_USER - your bot's user
* MATRIX_PASSWORD - your bot's password or access token
* MATRIX_ROOM_ID - the room ID you wish to send the report
* MATRIX_SUMMARY_ROOM_ID - the room ID you wish to send the summary
* STORE_PATH - directory for encryption keys
* SESSION_FILE - file to store session data

Line 401: time to send report
Line 405: time to send summary

Upon receiving the report, you can reply with [task] on [machine] completed

Both programs have been tested on our internal network on a Debian 12 PC with Python version 3.11.2 with 2 eIO controllers. Email version tested using gmail and outlook, matrix version tested with Matrix (Synapse) and Element (Windows and Android).
