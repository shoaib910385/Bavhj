import os
import asyncio
from telethon import TelegramClient, events, Button
from telethon.tl.functions.messages import ReportSpamRequest, ReportRequest
from telethon.tl.functions.contacts import BlockRequest, ResolveUsernameRequest
from telethon.tl.functions.channels import GetParticipantsRequest
from telethon.tl.types import ChannelParticipantsRecent
from telethon.tl.types import (
    InputReportReasonSpam,
    InputReportReasonViolence,
    InputReportReasonPornography,
    InputReportReasonChildAbuse,
    InputReportReasonCopyright,
    InputReportReasonGeoIrrelevant,
    InputReportReasonFake,
    InputReportReasonIllegalDrugs,
    InputReportReasonPersonalDetails,
    InputReportReasonOther
)
from telethon.errors import FloodWaitError, SessionPasswordNeededError
from telethon.tl.types import User, Channel, Chat
import csv
from datetime import datetime, timedelta
import re
import telethon  # Import telethon to check version

# Debug: Print the Telethon version and script path
print(f"Telethon version: {telethon.__version__}")
try:
    print(f"Script path: {os.path.abspath(__file__)}")
except NameError:
    print("Script path: Unable to determine (running in an interactive environment)")

# Bot token for the Telegram bot (replace with your bot token from @BotFather)
BOT_TOKEN = "8122837585:AAHM-fxBVAx1fCFPAav0sGTW3_B7bC_-ZLw"

# Account details for multiple reporting clients (with proxy support)
ACCOUNT_DETAILS = [
    {
        'phone': '+918000508717',
        'api_id': 22534224,
        'api_hash': 'ac2dbb91d4ab2412656ef13042a72266',
        'session': 'session_1',
        'proxy': None  # Proxy field added (None by default)
    },
    {
        'phone': '+917339877821',
        'api_id': 29116900,
        'api_hash': '4210bd5b2cfa9c3bca2896dd7bd3ebd6',
        'session': 'session_2',
        'proxy': None
    },
    {
        'phone': '+919352341204',
        'api_id': 23216053,
        'api_hash': '01160c6d5173253391a44b714f9e2be5',
        'session': 'session_3',
        'proxy': None
    },
]

# Store approved admin IDs (your Telegram user IDs)
ADMIN_IDS = [6862573769, 8014485309]

# Dictionary to store users approved via /sudo command with their expiry time
SUDO_APPROVED_USERS = {}  # Format: {user_id: expiry_datetime}

# Maximum reports per command per client
MAX_REPORTS = 50

# Dictionary to store username-to-ID mapping
username_to_id = {}

# Initialize the bot client (using bot token)
bot = TelegramClient('bot_session', ACCOUNT_DETAILS[0]['api_id'], ACCOUNT_DETAILS[0]['api_hash'])

# Initialize reporting clients for each account
reporting_clients = []

# Telegram official reporting reasons
REPORT_REASONS = [
    "spam",
    "violence",
    "pornography",
    "child_abuse",
    "copyright",
    "geo_irrelevant",
    "fake",
    "illegal_drugs",
    "personal_details",
    "other"
]

# Global variables for tracking total progress
total_reports_to_send = 0
total_reports_sent = 0
progress_message = None

# Function to create report reason buttons using Button.inline
def create_reason_buttons():
    buttons = []
    row = []
    for i, reason in enumerate(REPORT_REASONS):
        row.append(Button.inline(reason.capitalize(), data=f"reason_{reason}"))
        if (i + 1) % 2 == 0 or i == len(REPORT_REASONS) - 1:
            buttons.append(row)
            row = []
    return buttons

# Function to create phone number selection buttons
def create_phone_buttons():
    buttons = []
    row = []
    for i, account in enumerate(ACCOUNT_DETAILS):
        phone = account['phone']
        row.append(Button.inline(phone, data=f"phone_{phone}"))
        if (i + 1) % 2 == 0 or i == len(ACCOUNT_DETAILS) - 1:
            buttons.append(row)
            row = []
    return buttons

# Function to parse message link (e.g., https://t.me/username/123 or https://t.me/c/123456789/123)
def parse_message_link(link):
    # Regular expression to match Telegram message links
    # Matches: https://t.me/username/123 or https://t.me/c/123456789/123
    pattern = r"https://t\.me/(?:c/)?([^/]+)/(\d+)"
    match = re.match(pattern, link)
    if not match:
        return None, None
    chat_identifier, message_id = match.groups()
    return chat_identifier, int(message_id)

# Function to parse duration (e.g., "1 week", "2 days") into seconds
def parse_duration(duration_str):
    try:
        parts = duration_str.lower().split()
        if len(parts) != 2:
            raise ValueError("Invalid duration format")
        amount, unit = parts
        amount = int(amount)

        if unit in ["second", "seconds"]:
            return amount
        elif unit in ["minute", "minutes"]:
            return amount * 60
        elif unit in ["hour", "hours"]:
            return amount * 3600
        elif unit in ["day", "days"]:
            return amount * 86400
        elif unit in ["week", "weeks"]:
            return amount * 604800
        elif unit in ["month", "months"]:
            return amount * 2592000  # Approx 30 days
        else:
            raise ValueError("Invalid time unit")
    except Exception as e:
        raise ValueError(f"Error parsing duration: {str(e)}")

# Function to create a progress bar with green blocks (🟩) for filled, gray blocks (⬜) for unfilled, and report counts
def create_progress_bar(progress, total, width=20):
    filled = int(width * progress // total) if total > 0 else 0
    bar = '🟩' * filled + '⬜' * (width - filled)
    percentage = (progress / total * 100) if total > 0 else 0
    return f"[{bar}] {progress}/{total} ({percentage:.1f}%)"

# Function to update the global progress bar
async def update_progress_bar():
    global progress_message, total_reports_to_send, total_reports_sent
    if progress_message and total_reports_to_send > 0:
        progress_text = create_progress_bar(total_reports_sent, total_reports_to_send, width=20)
        buttons = [[Button.inline(progress_text, data="progress")]]
        await progress_message.edit(buttons=buttons)

# Background task to check for expired sudo approvals
async def check_sudo_expirations():
    while True:
        current_time = datetime.now()
        expired_users = []
        for user_id, expiry_time in SUDO_APPROVED_USERS.items():
            if current_time >= expiry_time:
                expired_users.append(user_id)
                print(f"User {user_id} sudo approval expired at {current_time}")

        for user_id in expired_users:
            # Remove the user from SUDO_APPROVED_USERS
            SUDO_APPROVED_USERS.pop(user_id, None)
            # Send message to the user
            try:
                await bot.send_message(
                    user_id,
                    "Your subscription has expired. To use it again please subscribe.\nContact: @Falling_angel69"
                )
                print(f"Sent expiration message to user {user_id}")
            except Exception as e:
                print(f"Failed to send expiration message to user {user_id}: {str(e)}")

        await asyncio.sleep(60)  # Check every minute

# Function to scan recent users in a chat and build username-to-ID mapping
async def scan_users(event, client):
    print("Scanning users in chat...")
    try:
        chat = await event.get_chat()
        if hasattr(chat, 'id'):
            participants = await client(GetParticipantsRequest(
                channel=chat.id,
                filter=ChannelParticipantsRecent(),
                offset=0,
                limit=200,
                hash=0
            ))
            for user in participants.users:
                if user.username:
                    username_to_id[user.username.lower()] = user.id
                    print(f"Mapped @{user.username} to ID {user.id}")
            await event.respond(f"Scanned {len(participants.users)} users. Username mapping updated.")
        else:
            await event.respond("This command can only be used in a group or channel.")
    except Exception as e:
        await event.respond(f"Error scanning users: {str(e)}")
        print(f"Error scanning users: {str(e)}")

# Function to count reports from a specific phone number
async def count_reports(event):
    print(f"Received /report_count command from user {event.sender_id}")
    if event.sender_id not in ADMIN_IDS:
        await event.respond('You are not authorized to use this command.')
        print("User not authorized for /report_count")
        return

    report_file = 'mass_reports.csv'
    report_counts = {account['phone']: 0 for account in ACCOUNT_DETAILS}

    if not os.path.isfile(report_file):
        await event.respond('No reports found for any account.')
        print(f"No report file found: {report_file}")
        return

    try:
        with open(report_file, 'r', encoding='utf-8') as file:
            reader = csv.reader(file)
            header = next(reader, None)
            if header is None:
                await event.respond('No reports found for any account.')
                print("Report file is empty")
                return

            for row in reader:
                if len(row) >= 2:
                    phone = row[1]
                    if phone in report_counts:
                        report_counts[phone] += 1

        response = "Total reports sent:\n"
        for phone, count in report_counts.items():
            response += f"{phone}: {count}\n"
        await event.respond(response.strip())
        print(f"Total reports: {report_counts}")
    except Exception as e:
        await event.respond(f'Error reading report count: {str(e)}')
        print(f"Error reading report file: {str(e)}")

# Function to resolve user entity for all clients
async def resolve_user(event):
    print(f"Received /resolve command from user {event.sender_id}")
    if event.sender_id not in ADMIN_IDS:
        await event.respond('You are not authorized to use this command.')
        print("User not authorized for /resolve")
        return

    user_input = event.message.message.split(' ')[1:]
    if not user_input:
        await event.respond('Please provide a username to resolve. Example: /resolve @username')
        print("No username provided")
        return

    username = user_input[0].lstrip('@')
    user_id = None
    username_lower = username.lower()

    try:
        print(f"Attempting to resolve @{username} with {reporting_clients[0][1]['phone']} using raw MTProto...")
        result = await reporting_clients[0][0](ResolveUsernameRequest(username_lower))
        user = None
        for u in result.users:
            if u.username and u.username.lower() == username_lower:
                user = u
                user_id = user.id
                username_to_id[username_lower] = user_id
                print(f"Resolved @{username} to ID {user_id} with {reporting_clients[0][1]['phone']}")
                break
        if not user:
            raise ValueError(f"User @{username} not found")
    except Exception as e:
        await event.respond(f'Failed to resolve @{username} with first client: {str(e)}')
        print(f"Failed to resolve @{username} with {reporting_clients[0][1]['phone']}: {str(e)}")
        return

    response = f"Accessibility check for @{username} (ID: {user_id}):\n"
    for client, account in reporting_clients:
        try:
            print(f"Verifying access to user ID {user_id} with {account['phone']} using raw MTProto...")
            result = await client(ResolveUsernameRequest(username_lower))
            user_found = False
            for u in result.users:
                if u.username and u.username.lower() == username_lower:
                    user_found = True
                    print(f"User ID {user_id} is accessible with {account['phone']}")
                    response += f"{account['phone']}: Accessible\n"
                    break
            if not user_found:
                raise ValueError(f"User @{username} not found with {account['phone']}")
        except Exception as e:
            response += f"{account['phone']}: Not accessible - {str(e)}\n"
            print(f"Cannot access user ID {user_id} with {account['phone']}: {str(e)}")

    response += "\nNote: If a client cannot access the user, they may have strict privacy settings."
    await event.respond(response)

# Function to handle /sudo command for approving new users
async def sudo_handler(event):
    print(f"Received /sudo command from user {event.sender_id}")
    # Allow only original admins (ADMIN_IDS) to use /sudo
    if event.sender_id not in ADMIN_IDS:
        await event.respond('You are not authorized to use this command.')
        print("User not authorized for /sudo")
        return

    # Extract the user to approve (by ID, username, or reply) and duration
    args = event.message.message.split()
    if len(args) < 2 and not event.message.is_reply:
        await event.respond('Please provide a user ID/username or reply to a user\'s message, followed by duration.\nExample: /sudo @username 1 week\nExample: /sudo 123456789 2 days')
        print("No user ID/username or duration provided for /sudo")
        return

    target_user_id = None
    duration_str = None

    # Check if user is specified via reply
    if event.message.is_reply:
        replied_msg = await event.get_reply_message()
        target_user_id = replied_msg.sender_id
        print(f"Target user ID from reply: {target_user_id}")
        # Duration should be in args[1] and args[2]
        if len(args) >= 3:
            duration_str = f"{args[1]} {args[2]}"
        else:
            duration_str = "1 month"  # Default duration
    else:
        # User specified via argument (ID or username)
        user_input = args[1]
        if user_input.startswith('@'):
            # Resolve username to ID
            username = user_input.lstrip('@').lower()
            try:
                result = await bot(ResolveUsernameRequest(username))
                for user in result.users:
                    if user.username and user.username.lower() == username:
                        target_user_id = user.id
                        print(f"Resolved @{username} to ID {target_user_id}")
                        break
                if not target_user_id:
                    await event.respond(f"Could not find user @{username}.")
                    print(f"User @{username} not found")
                    return
            except Exception as e:
                await event.respond(f"Error resolving @{username}: {str(e)}")
                print(f"Error resolving @{username}: {str(e)}")
                return
        else:
            # Assume it's a user ID
            try:
                target_user_id = int(user_input)
                print(f"Target user ID from argument: {target_user_id}")
            except ValueError:
                await event.respond('Invalid user ID or username. Please provide a valid Telegram user ID or username.\nExample: /sudo @username 1 week\nExample: /sudo 123456789 2 days')
                print("Invalid user ID or username provided")
                return

        # Extract duration
        if len(args) >= 4:
            duration_str = f"{args[2]} {args[3]}"
        else:
            duration_str = "1 month"  # Default duration

    # Parse duration
    try:
        duration_seconds = parse_duration(duration_str)
        expiry_time = datetime.now() + timedelta(seconds=duration_seconds)
        print(f"Parsed duration: {duration_str} = {duration_seconds} seconds, expires at {expiry_time}")
    except ValueError as e:
        await event.respond(f"Invalid duration format: {str(e)}\nExample: 1 week, 2 days, 3 hours")
        print(f"Error parsing duration: {str(e)}")
        return

    # Check if the user is already an admin or approved
    if target_user_id in ADMIN_IDS:
        await event.respond('This user is already an admin.')
        print(f"User {target_user_id} is already in ADMIN_IDS")
        return
    if target_user_id in SUDO_APPROVED_USERS:
        await event.respond('This user is already approved. Updating duration...')
        print(f"User {target_user_id} is already in SUDO_APPROVED_USERS, updating duration")
    else:
        await event.respond(f'User {target_user_id} has been approved to use reporting commands until {expiry_time.strftime("%Y-%m-d %H:%M:%S")}.')
        print(f"User {target_user_id} added to SUDO_APPROVED_USERS until {expiry_time}")

    # Approve the user with expiry time
    SUDO_APPROVED_USERS[target_user_id] = expiry_time

# Function to handle /unsudo command for removing approved users
async def unsudo_handler(event):
    print(f"Received /unsudo command from user {event.sender_id}")
    # Allow only original admins (ADMIN_IDS) to use /unsudo
    if event.sender_id not in ADMIN_IDS:
        await event.respond('You are not authorized to use this command.')
        print("User not authorized for /unsudo")
        return

    # Extract the user to remove (by ID, username, or reply)
    args = event.message.message.split()
    if len(args) < 2 and not event.message.is_reply:
        await event.respond('Please provide a user ID/username or reply to a user\'s message to remove them.\nExample: /unsudo @username\nExample: /unsudo 123456789')
        print("No user ID/username provided for /unsudo")
        return

    target_user_id = None

    # Check if user is specified via reply
    if event.message.is_reply:
        replied_msg = await event.get_reply_message()
        target_user_id = replied_msg.sender_id
        print(f"Target user ID from reply: {target_user_id}")
    else:
        # User specified via argument (ID or username)
        user_input = args[1]
        if user_input.startswith('@'):
            # Resolve username to ID
            username = user_input.lstrip('@').lower()
            try:
                result = await bot(ResolveUsernameRequest(username))
                for user in result.users:
                    if user.username and user.username.lower() == username:
                        target_user_id = user.id
                        print(f"Resolved @{username} to ID {target_user_id}")
                        break
                if not target_user_id:
                    await event.respond(f"Could not find user @{username}.")
                    print(f"User @{username} not found")
                    return
            except Exception as e:
                await event.respond(f"Error resolving @{username}: {str(e)}")
                print(f"Error resolving @{username}: {str(e)}")
                return
        else:
            # Assume it's a user ID
            try:
                target_user_id = int(user_input)
                print(f"Target user ID from argument: {target_user_id}")
            except ValueError:
                await event.respond('Invalid user ID or username. Please provide a valid Telegram user ID or username.\nExample: /unsudo @username\nExample: /unsudo 123456789')
                print("Invalid user ID or username provided")
                return

    # Check if the user is in SUDO_APPROVED_USERS
    if target_user_id not in SUDO_APPROVED_USERS:
        await event.respond('This user is not in the approved list.')
        print(f"User {target_user_id} not in SUDO_APPROVED_USERS")
        return

    # Remove the user
    SUDO_APPROVED_USERS.pop(target_user_id, None)
    await event.respond(f'User {target_user_id} has been removed from the approved list.')
    print(f"User {target_user_id} removed from SUDO_APPROVED_USERS")

# Function to send reports for a single client (Updated for Telethon 1.36.0)
async def send_reports_for_client(client, account, peer, username, report_count, reason, detailed_reason, event, message_id=None):
    global total_reports_sent
    successful_reports = 0
    report_file = 'mass_reports.csv'
    file_exists = os.path.isfile(report_file)

    # Clean the username by ensuring only one '@'
    cleaned_username = username.lstrip('@')
    cleaned_username = f"@{cleaned_username}"

    # Determine the entity type
    entity_type = "unknown"
    if isinstance(peer, User):
        entity_type = "user"
    elif isinstance(peer, Channel):
        entity_type = "channel"
    elif isinstance(peer, Chat):
        entity_type = "chat"

    for i in range(report_count):
        try:
            # Use the detailed reason if provided, otherwise fall back to a default message
            report_message = detailed_reason if detailed_reason else f"Reported for {reason.__class__.__name__}"

            # Debug: Print Telethon version before making the ReportRequest
            print(f"Using Telethon version {telethon.__version__} for ReportRequest")

            # Debug: Inspect the ReportRequest method signature
            import inspect
            print(f"ReportRequest method signature: {inspect.signature(ReportRequest)}")

            # Prepare parameters for ReportRequest (locked to Telethon 1.36.0 parameters)
            report_params = {
                "peer": peer,
                "id": [message_id] if message_id is not None else [1],
                "reason": reason,
                "message": report_message
            }

            if message_id is not None:
                # Report the specific message using ReportRequest
                print(f"Sending report {i+1}/{report_count} for message {message_id} in {cleaned_username} with {account['phone']}. Parameters: {report_params}")
                await client(ReportRequest(**report_params))
            else:
                if entity_type == "user":
                    # Use ReportSpamRequest for users
                    print(f"Sending spam report {i+1}/{report_count} for {cleaned_username} (type: {entity_type}) with {account['phone']}...")
                    await client(ReportSpamRequest(peer=peer))
                else:
                    # Use ReportRequest for channels and chats
                    print(f"Sending report {i+1}/{report_count} for {cleaned_username} (type: {entity_type}) with {account['phone']}. Parameters: {report_params}")
                    await client(ReportRequest(**report_params))

            # Block the user if it's a user and this is the first report (only for user reports, not message reports)
            if entity_type == "user" and i == 0 and message_id is None:
                print(f"Blocking {cleaned_username} with {account['phone']}...")
                await client(BlockRequest(id=peer))

            with open(report_file, 'a', newline='', encoding='utf-8') as file:
                writer = csv.writer(file)
                if not file_exists:
                    writer.writerow(['Username', 'Reported By Phone', 'Timestamp', 'Message ID'])
                    file_exists = True
                writer.writerow([cleaned_username, account['phone'], datetime.now().strftime('%Y-%m-d %H:%M:%S'), message_id if message_id else 'N/A'])

            successful_reports += 1
            total_reports_sent += 1

            if message_id is not None:
                print(f"Successfully reported message {message_id} in {cleaned_username} ({successful_reports}/{report_count}) with {account['phone']}")
            else:
                print(f"Successfully reported {cleaned_username} ({successful_reports}/{report_count}) with {account['phone']}")

            # Update global progress bar
            await update_progress_bar()

            print(f"Waiting 20 seconds before next report with {account['phone']}...")
            await asyncio.sleep(20)
        except FloodWaitError as e:
            wait_time = e.seconds
            print(f"Flood wait error for {account['phone']}: {wait_time} seconds")
            await event.respond(f"Flood wait error for {account['phone']}. Need to wait {wait_time} seconds. Stopping this account...")
            return successful_reports
        except Exception as e:
            print(f"Error during report {i+1} for {cleaned_username} with {account['phone']}: {str(e)}")
            await event.respond(f"Error during report {i+1} with {account['phone']}: {str(e)}. Stopping this account...")
            return successful_reports

    print(f"Completed reports for {cleaned_username} with {account['phone']}: {successful_reports}/{report_count} reports sent")
    return successful_reports

# Dictionary to store user states during conversation
user_states = {}

# Start the bot and reporting clients
async def main():
    # Start all reporting clients
    for account in ACCOUNT_DETAILS:
        print(f"Starting reporting client for {account['phone']}...")
        # Prepare proxy settings if available
        proxy = account.get('proxy')
        proxy_settings = None
        if proxy:
            proxy_settings = {
                'proxy_type': 'http',  # Assuming HTTP proxy (can be modified for SOCKS5 if needed)
                'addr': proxy['ip'],
                'port': proxy['port'],
                'username': proxy.get('username'),
                'password': proxy.get('password'),
                'rdns': True
            }
            print(f"Using proxy for {account['phone']}: {proxy}")

        client = TelegramClient(
            account['session'],
            account['api_id'],
            account['api_hash'],
            proxy=proxy_settings
        )
        await client.start(phone=account['phone'])
        print(f"Reporting client started for {account['phone']}")

        me = await client.get_me()
        print(f"Reporting client signed in as {me.phone}")
        reporting_clients.append((client, account))

    # Start the bot
    await bot.start(bot_token=BOT_TOKEN)
    print("Bot is running...")

    # Start the background task to check for sudo expirations
    asyncio.create_task(check_sudo_expirations())
    print("Started sudo expiration checker")

    # /start command to show report type buttons (accessible to admins and sudo users)
    @bot.on(events.NewMessage(pattern='/start'))
    async def start_handler(event):
        print(f"Received /start command from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            await event.respond('You are not authorized to use this command.')
            print("User not authorized for /start")
            return

        buttons = [
            [Button.inline("Report Channel", data="report_channel")],
            [Button.inline("Report Group", data="report_group")],
            [Button.inline("Report ID", data="report_id")],
            [Button.inline("Report Message", data="report_message")]
        ]
        await event.respond("Welcome to the Telegram Report Bot! Please select an option:", buttons=buttons)
        print("Responded to /start command with report type buttons")

    # Handle button clicks for report type (accessible to admins and sudo users)
    @bot.on(events.CallbackQuery(pattern='report_(channel|group|id|message)'))
    async def report_type_handler(event):
        print(f"Received callback query from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            await event.answer('You are not authorized to use this command.')
            print("User not authorized for callback")
            return

        report_type = event.data.decode('utf-8').split('_')[1]
        if report_type == "message":
            user_states[event.sender_id] = {'report_type': report_type, 'step': 'message_link'}
            await event.respond("Please provide the message link (e.g., https://t.me/username/123):")
        else:
            user_states[event.sender_id] = {'report_type': report_type, 'step': 'username'}
            await event.respond(f"Selected: Report {report_type.capitalize()}\nPlease enter the username/ID (e.g., @username):")
        await event.answer()

    # Handle user input for username, message link, report count, and detailed reason (accessible to admins and sudo users)
    @bot.on(events.NewMessage)
    async def handle_user_input(event):
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            return

        if event.sender_id not in user_states:
            return

        state = user_states[event.sender_id]
        step = state.get('step')

        if step == 'message_link':
            message_link = event.message.message.strip()
            chat_identifier, message_id = parse_message_link(message_link)
            if not chat_identifier or not message_id:
                await event.respond("Invalid message link. Please provide a valid link (e.g., https://t.me/username/123):")
                return
            state['chat_identifier'] = chat_identifier
            state['message_id'] = message_id
            state['step'] = 'report_count'
            await event.respond("Please enter the number of reports per account (1-50):")
            user_states[event.sender_id] = state

        elif step == 'username':
            username = event.message.message.strip()
            if not username.startswith('@'):
                username = f"@{username}"
            state['username'] = username
            state['step'] = 'report_count'
            await event.respond("Please enter the number of reports per account (1-50):")
            user_states[event.sender_id] = state

        elif step == 'report_count':
            try:
                report_count = int(event.message.message)
                if report_count <= 0 or report_count > MAX_REPORTS:
                    raise ValueError
                state['report_count'] = report_count
                state['step'] = 'reason'
                print(f"Set report_count to {report_count} for user {event.sender_id}")
                buttons = create_reason_buttons()
                await event.respond("Please select a reason for reporting:", buttons=buttons)
            except ValueError:
                await event.respond(f"Report count must be a number between 1 and {MAX_REPORTS}. Please try again:")
            user_states[event.sender_id] = state

        elif step == 'detailed_reason':
            detailed_reason = event.message.message.strip()
            state['detailed_reason'] = detailed_reason
            user_states[event.sender_id] = state

            # Start the mass reporting process
            global total_reports_to_send, total_reports_sent, progress_message
            total_reports_sent = 0
            report_type = state['report_type']
            report_count = state['report_count']
            total_reports_to_send = report_count * len(reporting_clients)

            if report_type == "message":
                chat_identifier = state['chat_identifier']
                message_id = state['message_id']
                await event.respond(f"Starting mass report for message {message_id} in chat {chat_identifier} with reason: {state['reason'].capitalize()}...")
            else:
                username = state['username']
                cleaned_username = username.lstrip('@')
                cleaned_username = f"@{cleaned_username}"
                await event.respond(f"Starting mass report for {cleaned_username} with reason: {state['reason'].capitalize()}...")

            # Initialize the progress bar
            progress_message = await event.respond("Progress:", buttons=[[Button.inline("[🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜] 0/0 (0.0%)", data="progress")]])

            # Extract details
            report_count = state['report_count']
            report_type = state['report_type']
            reason = state['reason']
            detailed_reason = state['detailed_reason']

            # Map reason to Telegram's InputReportReason
            reason_map = {
                "spam": InputReportReasonSpam(),
                "violence": InputReportReasonViolence(),
                "pornography": InputReportReasonPornography(),
                "child_abuse": InputReportReasonChildAbuse(),
                "copyright": InputReportReasonCopyright(),
                "geo_irrelevant": InputReportReasonGeoIrrelevant(),
                "fake": InputReportReasonFake(),
                "illegal_drugs": InputReportReasonIllegalDrugs(),
                "personal_details": InputReportReasonPersonalDetails(),
                "other": InputReportReasonOther()
            }
            report_reason = reason_map.get(reason, InputReportReasonSpam())

            # Handle message reporting
            if report_type == "message":
                try:
                    # Resolve the chat using the first client
                    chat_identifier_lower = chat_identifier.lower()
                    result = await reporting_clients[0][0](ResolveUsernameRequest(chat_identifier_lower))
                    entity = None
                    for chat in result.chats:
                        if chat.username and chat.username.lower() == chat_identifier_lower:
                            entity = chat
                            print(f"Resolved chat {chat_identifier} to ID {entity.id} using raw MTProto")
                            break
                    for user in result.users:
                        if user.username and user.username.lower() == chat_identifier_lower:
                            entity = user
                            print(f"Resolved user {chat_identifier} to ID {entity.id} using raw MTProto")
                            break

                    if not entity:
                        raise ValueError(f"Chat/User {chat_identifier} not found")

                    # Run all clients concurrently
                    tasks = []
                    for client, account in reporting_clients:
                        try:
                            # Resolve the chat for each client
                            result = await client(ResolveUsernameRequest(chat_identifier_lower))
                            peer_for_client = None
                            for chat in result.chats:
                                if chat.username and chat.username.lower() == chat_identifier_lower:
                                    peer_for_client = chat
                                    print(f"Chat ID {chat.id} resolved with {account['phone']} using raw MTProto")
                                    break
                            for user in result.users:
                                if user.username and user.username.lower() == chat_identifier_lower:
                                    peer_for_client = user
                                    print(f"User ID {user.id} resolved with {account['phone']} using raw MTProto")
                                    break

                            if not peer_for_client:
                                raise ValueError(f"Chat/User {chat_identifier} not found with {account['phone']}")

                        except FloodWaitError as e:
                            wait_time = e.seconds
                            await event.respond(f'Flood wait error for {account["phone"]}. Need to wait {wait_time} seconds. Skipping...')
                            print(f"Flood wait error for {account['phone']}: {wait_time} seconds")
                            continue
                        except Exception as e:
                            await event.respond(f'Cannot access {chat_identifier} with {account["phone"]}: {str(e)}. Skipping...')
                            print(f"Cannot access {chat_identifier} with {account['phone']}: {str(e)}")
                            continue

                        task = asyncio.create_task(
                            send_reports_for_client(
                                client,
                                account,
                                peer_for_client,
                                f"@{chat_identifier}",
                                report_count,
                                report_reason,
                                detailed_reason,
                                event,
                                message_id=message_id
                            )
                        )
                        tasks.append(task)

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    total_successful_reports = sum(result for result in results if isinstance(result, int))

                    # Send final message, but keep the progress bar
                    await event.respond(f"{total_successful_reports} reports have been sent.")
                    print(f"All accounts completed for message {message_id} in {chat_identifier}: {total_successful_reports}/{report_count * len(tasks)} reports sent")

                    # Reset user state
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

                except ValueError:
                    await event.respond(f'Invalid chat or entity not found: {chat_identifier}.')
                    print(f"Invalid chat: {chat_identifier}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0
                except Exception as e:
                    await event.respond(f'Error processing message {message_id} in {chat_identifier}: {str(e)}')
                    print(f"Error in mass report for message {message_id} in {chat_identifier}: {str(e)}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

            # Handle user/channel/group reporting (original logic)
            else:
                username = state['username']
                username_lower = username.lower().lstrip('@')
                try:
                    # Use the first client to resolve the username
                    result = await reporting_clients[0][0](ResolveUsernameRequest(username_lower))
                    entity = None
                    for user in result.users:
                        if user.username and user.username.lower() == username_lower:
                            entity = user
                            username_to_id[username_lower] = entity.id
                            print(f"Resolved {username} to ID {entity.id} using raw MTProto")
                            break

                    if not entity:
                        raise ValueError(f"User {username} not found")

                    # Run all clients concurrently
                    tasks = []
                    for client, account in reporting_clients:
                        try:
                            # Use raw MTProto to resolve the entity for each client
                            result = await client(ResolveUsernameRequest(username_lower))
                            peer_for_client = None
                            for user in result.users:
                                if user.username and user.username.lower() == username_lower:
                                    peer_for_client = user
                                    print(f"Entity ID {user.id} resolved with {account['phone']} using raw MTProto")
                                    break

                            if not peer_for_client:
                                raise ValueError(f"User {username} not found with {account['phone']}")

                        except FloodWaitError as e:
                            wait_time = e.seconds
                            await event.respond(f'Flood wait error for {account["phone"]}. Need to wait {wait_time} seconds. Skipping...')
                            print(f"Flood wait error for {account['phone']}: {wait_time} seconds")
                            continue
                        except Exception as e:
                            await event.respond(f'Cannot access {cleaned_username} with {account["phone"]}: {str(e)}. Skipping...')
                            print(f"Cannot access {cleaned_username} with {account['phone']}: {str(e)}")
                            continue

                        task = asyncio.create_task(
                            send_reports_for_client(
                                client,
                                account,
                                peer_for_client,
                                username,
                                report_count,
                                report_reason,
                                detailed_reason,
                                event
                            )
                        )
                        tasks.append(task)

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    total_successful_reports = sum(result for result in results if isinstance(result, int))

                    # Send final message, but keep the progress bar
                    await event.respond(f"{total_successful_reports} reports have been sent.")
                    print(f"All accounts completed for {cleaned_username}: {total_successful_reports}/{report_count * len(tasks)} reports sent")

                    # Reset user state
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

                except ValueError:
                    await event.respond(f'Invalid username or entity not found: {cleaned_username}.')
                    print(f"Invalid username: {cleaned_username}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0
                except Exception as e:
                    await event.respond(f'Error processing {cleaned_username}: {str(e)}')
                    print(f"Error in mass report for {cleaned_username}: {str(e)}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

        # Handle /add command steps (accessible to admins only)
        elif step == 'add_phone':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for add_phone step")
                return
            phone = event.message.message.strip()
            if not phone.startswith('+'):
                await event.respond("Phone number must start with a country code (e.g., +1234567890). Please try again:")
                return
            state['new_account'] = {'phone': phone, 'proxy': None}
            state['step'] = 'add_api_id'
            await event.respond("Please enter the API ID:")
            user_states[event.sender_id] = state

        elif step == 'add_api_id':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for add_api_id step")
                return
            try:
                api_id = int(event.message.message)
                state['new_account']['api_id'] = api_id
                state['step'] = 'add_api_hash'
                await event.respond("Please enter the API Hash:")
                user_states[event.sender_id] = state
            except ValueError:
                await event.respond("API ID must be a number. Please try again:")
                return

        elif step == 'add_api_hash':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for add_api_hash step")
                return
            api_hash = event.message.message.strip()
            state['new_account']['api_hash'] = api_hash
            state['step'] = 'add_session'
            await event.respond("Please enter the session name (e.g., session_4):")
            user_states[event.sender_id] = state

        elif step == 'add_session':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for add_session step")
                return
            session = event.message.message.strip()
            state['new_account']['session'] = session

            # Add the new account to ACCOUNT_DETAILS and start a new client
            new_account = state['new_account']
            ACCOUNT_DETAILS.append(new_account)
            print(f"Added new account to ACCOUNT_DETAILS: {new_account}")

            # Create a Telethon client for the new account
            client = TelegramClient(
                new_account['session'],
                new_account['api_id'],
                new_account['api_hash']
            )

            try:
                # Connect the client and request the verification code
                await client.connect()
                sent_code = await client.send_code_request(new_account['phone'])
                print(f"Sent verification code request for {new_account['phone']}, phone_code_hash: {sent_code.phone_code_hash}")

                # Store the phone_code_hash in the user state
                state['phone_code_hash'] = sent_code.phone_code_hash
                state['step'] = 'add_verification_code'
                user_states[event.sender_id] = state
                await event.respond(f"A verification code has been sent to {new_account['phone']}. Please enter the code you received (or type /cancel to abort):")

            except FloodWaitError as e:
                wait_time = e.seconds
                await event.respond(f"Flood wait error: Please wait {wait_time} seconds before trying again.")
                print(f"Flood wait error for {new_account['phone']}: {wait_time} seconds")
                ACCOUNT_DETAILS.remove(new_account)
                user_states.pop(event.sender_id, None)
            except Exception as e:
                await event.respond(f"Failed to send code request for {new_account['phone']}: {str(e)}")
                print(f"Error sending code request for {new_account['phone']}: {str(e)}")
                ACCOUNT_DETAILS.remove(new_account)
                user_states.pop(event.sender_id, None)

        elif step == 'add_verification_code':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for add_verification_code step")
                return

            code = event.message.message.strip()
            new_account = state['new_account']
            phone_code_hash = state.get('phone_code_hash')

            if not phone_code_hash:
                await event.respond("Error: Phone code hash not found. Please start the /add process again.")
                print("Phone code hash not found in user state")
                ACCOUNT_DETAILS.remove(new_account)
                user_states.pop(event.sender_id, None)
                return

            # Create the client again (since we need to sign in with the code)
            client = TelegramClient(
                new_account['session'],
                new_account['api_id'],
                new_account['api_hash']
            )

            try:
                await client.connect()
                # Sign in with the verification code and phone_code_hash
                await client.sign_in(
                    phone=new_account['phone'],
                    code=code,
                    phone_code_hash=phone_code_hash
                )
                print(f"Successfully signed in for {new_account['phone']}")

                # Add the client to the reporting clients list
                me = await client.get_me()
                print(f"Reporting client signed in as {me.phone}")
                reporting_clients.append((client, new_account))
                await event.respond(f"Successfully added account with phone {new_account['phone']}.")

            except SessionPasswordNeededError:
                await event.respond(f"Two-step verification is enabled for {new_account['phone']}. This bot does not support accounts with 2FA at the moment. Please remove 2FA or use a different account.")
                print(f"Two-step verification required for {new_account['phone']}")
                await client.disconnect()
                ACCOUNT_DETAILS.remove(new_account)
            except Exception as e:
                await event.respond(f"Failed to sign in for {new_account['phone']}: {str(e)}")
                print(f"Error signing in for {new_account['phone']}: {str(e)}")
                await client.disconnect()
                ACCOUNT_DETAILS.remove(new_account)

            # Reset user state
            user_states.pop(event.sender_id, None)

        # Handle /delete command step (accessible to admins only)
        elif step == 'delete_phone':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for delete_phone step")
                return
            phone = event.message.message.strip()
            # Find the account in ACCOUNT_DETAILS
            account_to_remove = None
            for account in ACCOUNT_DETAILS:
                if account['phone'] == phone:
                    account_to_remove = account
                    break

            if not account_to_remove:
                await event.respond(f"No account found with phone number {phone}.")
                user_states.pop(event.sender_id, None)
                return

            # Remove the account from ACCOUNT_DETAILS and disconnect the client
            session_name = account_to_remove['session']
            ACCOUNT_DETAILS.remove(account_to_remove)
            for client, acc in reporting_clients:
                if acc['phone'] == phone:
                    await client.disconnect()
                    reporting_clients.remove((client, acc))
                    print(f"Disconnected and removed client for {phone}")
                    break

            # Delete the session file
            session_file = f"{session_name}.session"
            try:
                if os.path.exists(session_file):
                    os.remove(session_file)
                    print(f"Successfully deleted session file: {session_file}")
                    await event.respond(f"Successfully removed account with phone {phone} and deleted session file {session_file}.")
                else:
                    print(f"Session file {session_file} not found, but account {phone} was removed.")
                    await event.respond(f"Successfully removed account with phone {phone}. Session file {session_file} was not found.")
            except Exception as e:
                print(f"Error deleting session file {session_file}: {str(e)}")
                await event.respond(f"Successfully removed account with phone {phone}, but failed to delete session file {session_file}: {str(e)}")

            user_states.pop(event.sender_id, None)

        # Handle /addproxy command steps (accessible to admins only)
        elif step == 'addproxy_ip':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for addproxy_ip step")
                return
            ip = event.message.message.strip()
            state['proxy_details'] = {'ip': ip}
            state['step'] = 'addproxy_port'
            await event.respond("Please enter the proxy port (e.g., 8080):")
            user_states[event.sender_id] = state

        elif step == 'addproxy_port':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for addproxy_port step")
                return
            try:
                port = int(event.message.message)
                state['proxy_details']['port'] = port
                state['step'] = 'addproxy_username'
                await event.respond("Please enter the proxy username (or type /skip if none):")
                user_states[event.sender_id] = state
            except ValueError:
                await event.respond("Port must be a number. Please try again:")
                return

        elif step == 'addproxy_username':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for addproxy_username step")
                return
            username = event.message.message.strip()
            state['proxy_details']['username'] = username if username else None
            state['step'] = 'addproxy_password'
            await event.respond("Please enter the proxy password (or type /skip if none):")
            user_states[event.sender_id] = state

        elif step == 'addproxy_password':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for addproxy_password step")
                return
            password = event.message.message.strip()
            state['proxy_details']['password'] = password if password else None

            # Find the account and update proxy details
            phone = state['selected_phone']
            for account in ACCOUNT_DETAILS:
                if account['phone'] == phone:
                    account['proxy'] = state['proxy_details']
                    print(f"Added proxy to account {phone}: {account['proxy']}")
                    break

            # Disconnect and restart the client with the new proxy
            for client, acc in reporting_clients:
                if acc['phone'] == phone:
                    await client.disconnect()
                    reporting_clients.remove((client, acc))
                    print(f"Disconnected client for {phone}")
                    break

            # Restart the client with the new proxy
            for account in ACCOUNT_DETAILS:
                if account['phone'] == phone:
                    proxy_settings = None
                    if account['proxy']:
                        proxy_settings = {
                            'proxy_type': 'http',
                            'addr': account['proxy']['ip'],
                            'port': account['proxy']['port'],
                            'username': account['proxy'].get('username'),
                            'password': account['proxy'].get('password'),
                            'rdns': True
                        }
                    try:
                        new_client = TelegramClient(
                            account['session'],
                            account['api_id'],
                            account['api_hash'],
                            proxy=proxy_settings
                        )
                        await new_client.start(phone=account['phone'])
                        print(f"Restarted client for {account['phone']} with proxy {proxy_settings}")
                        me = await new_client.get_me()
                        print(f"Reporting client signed in as {me.phone}")
                        reporting_clients.append((new_client, account))
                        await event.respond(f"Successfully added proxy to account {phone} and restarted client.")
                    except Exception as e:
                        await event.respond(f"Failed to restart client for {phone} with proxy: {str(e)}")
                        print(f"Error restarting client for {phone}: {str(e)}")
                        # Remove proxy if client fails to start
                        account['proxy'] = None
                    break

            # Reset user state
            user_states.pop(event.sender_id, None)

    # Handle reason selection (accessible to admins and sudo users)
    @bot.on(events.CallbackQuery(pattern='reason_.*'))
    async def reason_handler(event):
        print(f"Received reason callback query from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            await event.answer('You are not authorized to use this command.')
            print("User not authorized for reason callback")
            return

        if event.sender_id not in user_states or user_states[event.sender_id].get('step') != 'reason':
            await event.answer('Invalid state. Please start over with /start.')
            return

        reason = event.data.decode('utf-8').split('_')[1]
        state = user_states[event.sender_id]
        state['reason'] = reason
        state['step'] = 'detailed_reason'
        user_states[event.sender_id] = state

        await event.respond("Please provide an optional detailed reason for reporting (or type /skip to proceed):")
        await event.answer()

    # Handle phone number selection for /addproxy (accessible to admins only)
    @bot.on(events.CallbackQuery(pattern='phone_.*'))
    async def phone_handler(event):
        print(f"Received phone callback query from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS:
            await event.answer('You are not authorized to use this command.')
            print("User not authorized for phone callback")
            return

        if event.sender_id not in user_states or user_states[event.sender_id].get('step') != 'select_phone':
            await event.answer('Invalid state. Please start over with /addproxy.')
            return

        phone = event.data.decode('utf-8').split('_')[1]
        state = user_states[event.sender_id]
        state['selected_phone'] = phone
        state['step'] = 'addproxy_ip'
        user_states[event.sender_id] = state

        await event.respond(f"Selected phone: {phone}\nPlease enter the proxy IP address (e.g., 192.168.1.1):")
        await event.answer()

    # Handle /skip command to skip optional proxy fields or detailed reason (accessible to admins and sudo users for reporting, admins for proxy)
    @bot.on(events.NewMessage(pattern='/skip'))
    async def skip_handler(event):
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            return

        if event.sender_id not in user_states:
            return

        state = user_states[event.sender_id]
        step = state.get('step')

        if step == 'detailed_reason':
            state['detailed_reason'] = ""
            user_states[event.sender_id] = state

            # Start the mass reporting process
            global total_reports_to_send, total_reports_sent, progress_message
            total_reports_sent = 0
            report_type = state['report_type']
            report_count = state['report_count']
            total_reports_to_send = report_count * len(reporting_clients)

            if report_type == "message":
                chat_identifier = state['chat_identifier']
                message_id = state['message_id']
                await event.respond(f"Starting mass report for message {message_id} in chat {chat_identifier} with reason: {state['reason'].capitalize()}...")
            else:
                username = state['username']
                cleaned_username = username.lstrip('@')
                cleaned_username = f"@{cleaned_username}"
                await event.respond(f"Starting mass report for {cleaned_username} with reason: {state['reason'].capitalize()}...")

            # Initialize the progress bar
            progress_message = await event.respond("Progress:", buttons=[[Button.inline("[🟩🟩🟩🟩🟩⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜⬜] 0/0 (0.0%)", data="progress")]])

            # Extract details
            report_count = state['report_count']
            report_type = state['report_type']
            reason = state['reason']
            detailed_reason = state['detailed_reason']

            # Map reason to Telegram's InputReportReason
            reason_map = {
                "spam": InputReportReasonSpam(),
                "violence": InputReportReasonViolence(),
                "pornography": InputReportReasonPornography(),
                "child_abuse": InputReportReasonChildAbuse(),
                "copyright": InputReportReasonCopyright(),
                "geo_irrelevant": InputReportReasonGeoIrrelevant(),
                "fake": InputReportReasonFake(),
                "illegal_drugs": InputReportReasonIllegalDrugs(),
                "personal_details": InputReportReasonPersonalDetails(),
                "other": InputReportReasonOther()
            }
            report_reason = reason_map.get(reason, InputReportReasonSpam())

            # Handle message reporting
            if report_type == "message":
                try:
                    # Resolve the chat using the first client
                    chat_identifier_lower = chat_identifier.lower()
                    result = await reporting_clients[0][0](ResolveUsernameRequest(chat_identifier_lower))
                    entity = None
                    for chat in result.chats:
                        if chat.username and chat.username.lower() == chat_identifier_lower:
                            entity = chat
                            print(f"Resolved chat {chat_identifier} to ID {entity.id} using raw MTProto")
                            break
                    for user in result.users:
                        if user.username and user.username.lower() == chat_identifier_lower:
                            entity = user
                            print(f"Resolved user {chat_identifier} to ID {entity.id} using raw MTProto")
                            break

                    if not entity:
                        raise ValueError(f"Chat/User {chat_identifier} not found")

                    # Run all clients concurrently
                    tasks = []
                    for client, account in reporting_clients:
                        try:
                            # Resolve the chat for each client
                            result = await client(ResolveUsernameRequest(chat_identifier_lower))
                            peer_for_client = None
                            for chat in result.chats:
                                if chat.username and chat.username.lower() == chat_identifier_lower:
                                    peer_for_client = chat
                                    print(f"Chat ID {chat.id} resolved with {account['phone']} using raw MTProto")
                                    break
                            for user in result.users:
                                if user.username and user.username.lower() == chat_identifier_lower:
                                    peer_for_client = user
                                    print(f"User ID {user.id} resolved with {account['phone']} using raw MTProto")
                                    break

                            if not peer_for_client:
                                raise ValueError(f"Chat/User {chat_identifier} not found with {account['phone']}")

                        except FloodWaitError as e:
                            wait_time = e.seconds
                            await event.respond(f'Flood wait error for {account["phone"]}. Need to wait {wait_time} seconds. Skipping...')
                            print(f"Flood wait error for {account['phone']}: {wait_time} seconds")
                            continue
                        except Exception as e:
                            await event.respond(f'Cannot access {chat_identifier} with {account["phone"]}: {str(e)}. Skipping...')
                            print(f"Cannot access {chat_identifier} with {account['phone']}: {str(e)}")
                            continue

                        task = asyncio.create_task(
                            send_reports_for_client(
                                client,
                                account,
                                peer_for_client,
                                f"@{chat_identifier}",
                                report_count,
                                report_reason,
                                detailed_reason,
                                event,
                                message_id=message_id
                            )
                        )
                        tasks.append(task)

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    total_successful_reports = sum(result for result in results if isinstance(result, int))

                    # Send final message, but keep the progress bar
                    await event.respond(f"{total_successful_reports} reports have been sent.")
                    print(f"All accounts completed for message {message_id} in {chat_identifier}: {total_successful_reports}/{report_count * len(tasks)} reports sent")

                    # Reset user state
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

                except ValueError:
                    await event.respond(f'Invalid chat or entity not found: {chat_identifier}.')
                    print(f"Invalid chat: {chat_identifier}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0
                except Exception as e:
                    await event.respond(f'Error processing message {message_id} in {chat_identifier}: {str(e)}')
                    print(f"Error in mass report for message {message_id} in {chat_identifier}: {str(e)}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

            # Handle user/channel/group reporting (original logic)
            else:
                username = state['username']
                username_lower = username.lower().lstrip('@')
                try:
                    # Use the first client to resolve the username
                    result = await reporting_clients[0][0](ResolveUsernameRequest(username_lower))
                    entity = None
                    for user in result.users:
                        if user.username and user.username.lower() == username_lower:
                            entity = user
                            username_to_id[username_lower] = entity.id
                            print(f"Resolved {username} to ID {entity.id} using raw MTProto")
                            break

                    if not entity:
                        raise ValueError(f"User {username} not found")

                    # Run all clients concurrently
                    tasks = []
                    for client, account in reporting_clients:
                        try:
                            # Use raw MTProto to resolve the entity for each client
                            result = await client(ResolveUsernameRequest(username_lower))
                            peer_for_client = None
                            for user in result.users:
                                if user.username and user.username.lower() == username_lower:
                                    peer_for_client = user
                                    print(f"Entity ID {user.id} resolved with {account['phone']} using raw MTProto")
                                    break

                            if not peer_for_client:
                                raise ValueError(f"User {username} not found with {account['phone']}")

                        except FloodWaitError as e:
                            wait_time = e.seconds
                            await event.respond(f'Flood wait error for {account["phone"]}. Need to wait {wait_time} seconds. Skipping...')
                            print(f"Flood wait error for {account['phone']}: {wait_time} seconds")
                            continue
                        except Exception as e:
                            await event.respond(f'Cannot access {cleaned_username} with {account["phone"]}: {str(e)}. Skipping...')
                            print(f"Cannot access {cleaned_username} with {account['phone']}: {str(e)}")
                            continue

                        task = asyncio.create_task(
                            send_reports_for_client(
                                client,
                                account,
                                peer_for_client,
                                username,
                                report_count,
                                report_reason,
                                detailed_reason,
                                event
                            )
                        )
                        tasks.append(task)

                    results = await asyncio.gather(*tasks, return_exceptions=True)
                    total_successful_reports = sum(result for result in results if isinstance(result, int))

                    # Send final message, but keep the progress bar
                    await event.respond(f"{total_successful_reports} reports have been sent.")
                    print(f"All accounts completed for {cleaned_username}: {total_successful_reports}/{report_count * len(tasks)} reports sent")

                    # Reset user state
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

                except ValueError:
                    await event.respond(f'Invalid username or entity not found: {cleaned_username}.')
                    print(f"Invalid username: {cleaned_username}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0
                except Exception as e:
                    await event.respond(f'Error processing {cleaned_username}: {str(e)}')
                    print(f"Error in mass report for {cleaned_username}: {str(e)}")
                    user_states.pop(event.sender_id, None)
                    progress_message = None
                    total_reports_to_send = 0
                    total_reports_sent = 0

        elif step == 'addproxy_username':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for addproxy_username step")
                return
            state['proxy_details']['username'] = None
            state['step'] = 'addproxy_password'
            await event.respond("Please enter the proxy password (or type /skip if none):")
            user_states[event.sender_id] = state

        elif step == 'addproxy_password':
            if event.sender_id not in ADMIN_IDS:
                await event.respond('You are not authorized to use this command.')
                print("User not authorized for addproxy_password step")
                return
            state['proxy_details']['password'] = None

            # Find the account and update proxy details
            phone = state['selected_phone']
            for account in ACCOUNT_DETAILS:
                if account['phone'] == phone:
                    account['proxy'] = state['proxy_details']
                    print(f"Added proxy to account {phone}: {account['proxy']}")
                    break

            # Disconnect and restart the client with the new proxy
            for client, acc in reporting_clients:
                if acc['phone'] == phone:
                    await client.disconnect()
                    reporting_clients.remove((client, acc))
                    print(f"Disconnected client for {phone}")
                    break

            # Restart the client with the new proxy
            for account in ACCOUNT_DETAILS:
                if account['phone'] == phone:
                    proxy_settings = None
                    if account['proxy']:
                        proxy_settings = {
                            'proxy_type': 'http',
                            'addr': account['proxy']['ip'],
                            'port': account['proxy']['port'],
                            'username': account['proxy'].get('username'),
                            'password': account['proxy'].get('password'),
                            'rdns': True
                        }
                    try:
                        new_client = TelegramClient(
                            account['session'],
                            account['api_id'],
                            account['api_hash'],
                            proxy=proxy_settings
                        )
                        await new_client.start(phone=account['phone'])
                        print(f"Restarted client for {account['phone']} with proxy {proxy_settings}")
                        me = await new_client.get_me()
                        print(f"Reporting client signed in as {me.phone}")
                        reporting_clients.append((new_client, account))
                        await event.respond(f"Successfully added proxy to account {phone} and restarted client.")
                    except Exception as e:
                        await event.respond(f"Failed to restart client for {phone} with proxy: {str(e)}")
                        print(f"Error restarting client for {phone}: {str(e)}")
                        # Remove proxy if client fails to start
                        account['proxy'] = None
                    break

            # Reset user state
            user_states.pop(event.sender_id, None)

    # Add a /cancel command to cancel ongoing operations (accessible to admins and sudo users)
    @bot.on(events.NewMessage(pattern='/cancel'))
    async def cancel_handler(event):
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            return

        if event.sender_id in user_states:
            user_states.pop(event.sender_id, None)
            await event.respond("Operation cancelled.")
        else:
            await event.respond("No ongoing operation to cancel.")

    # Add a /scan command to build username-to-ID mapping (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/scan'))
    async def scan_handler(event):
        print(f"Received /scan command from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS:
            await event.respond('You are not authorized to use this command.')
            print("User not authorized for /scan")
            return
        await scan_users(event, reporting_clients[0][0])

    # Add a /resolve command to check user accessibility (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/resolve'))
    async def resolve_handler(event):
        print("Handler triggered for /resolve command")
        await resolve_user(event)

    # Add a /report_count command to check total reports (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/report_count'))
    async def report_count_handler(event):
        print("Handler triggered for /report_count command")
        await count_reports(event)

    # Add a /sudo command to approve new users (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/sudo'))
    async def sudo_command_handler(event):
        print("Handler triggered for /sudo command")
        await sudo_handler(event)

    # Add a /unsudo command to remove approved users (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/unsudo'))
    async def unsudo_command_handler(event):
        print("Handler triggered for /unsudo command")
        await unsudo_handler(event)

    # Add a /add command to add a new mobile number (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/add'))
    async def add_handler(event):
        print(f"Received /add command from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS:
            await event.respond('You are not authorized to use this command.')
            print("User not authorized for /add")
            return

        user_states[event.sender_id] = {'step': 'add_phone'}
        await event.respond("Please enter the phone number (e.g., +1234567890):")

    # Add a /delete command to remove a mobile number (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/delete'))
    async def delete_handler(event):
        print(f"Received /delete command from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS:
            await event.respond('You are not authorized to use this command.')
            print("User not authorized for /delete")
            return

        user_states[event.sender_id] = {'step': 'delete_phone'}
        await event.respond("Please enter the phone number to delete (e.g., +1234567890):")

    # Add a /list command to show all registered phone numbers (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/list'))
    async def list_handler(event):
        print(f"Received /list command from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS:
            await event.respond('You are not authorized to use this command.')
            print("User not authorized for /list")
            return

        if not ACCOUNT_DETAILS:
            await event.respond("No accounts registered.")
            return

        response = "Registered phone numbers:\n"
        for account in ACCOUNT_DETAILS:
            phone = account['phone']
            proxy_status = "No proxy" if not account['proxy'] else f"Proxy: {account['proxy']['ip']}:{account['proxy']['port']}"
            response += f"- {phone} ({proxy_status})\n"
        await event.respond(response.strip())

    # Add a /addproxy command to add proxy details for a phone number (accessible to admins only)
    @bot.on(events.NewMessage(pattern='/addproxy'))
    async def addproxy_handler(event):
        print(f"Received /addproxy command from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS:
            await event.respond('You are not authorized to use this command.')
            print("User not authorized for /addproxy")
            return

        if not ACCOUNT_DETAILS:
            await event.respond("No accounts registered. Please add an account using /add first.")
            return

        user_states[event.sender_id] = {'step': 'select_phone'}
        buttons = create_phone_buttons()
        await event.respond("Please select a phone number to add a proxy to:", buttons=buttons)

    # Add a /function command to list all commands (accessible to admins and sudo users, with restrictions for sudo users)
    @bot.on(events.NewMessage(pattern='/function'))
    async def function_handler(event):
        print(f"Received /function command from user {event.sender_id}")
        if event.sender_id not in ADMIN_IDS and event.sender_id not in SUDO_APPROVED_USERS:
            await event.respond('You are not authorized to use this command.')
            print("User not authorized for /function")
            return

        # Define all commands with descriptions
        all_commands = [
            ("/start", "Start the reporting process for a channel, group, ID, or message."),
            ("/function", "List all available commands (this command)."),
            ("/sudo", "Approve a user to use reporting commands for a specified duration (admin only)."),
            ("/unsudo", "Remove a user from the approved list (admin only)."),
            ("/add", "Add a new phone number for reporting (admin only)."),
            ("/delete", "Remove a phone number from the reporting list (admin only)."),
            ("/list", "Show all registered phone numbers (admin only)."),
            ("/addproxy", "Add proxy details for a phone number (admin only)."),
            ("/scan", "Scan recent users in a chat to build username-to-ID mapping (admin only)."),
            ("/resolve", "Check if a username is accessible by all clients (admin only)."),
            ("/report_count", "Show the total number of reports sent by each phone number (admin only)."),
        ]

        # Filter commands based on user type
        if event.sender_id in ADMIN_IDS:
            # Admins can see all commands
            response = "Available commands:\n"
            for command, description in all_commands:
                response += f"{command} - {description}\n"
        else:
            # Sudo users can only see reporting-related commands
            response = "Available commands (for sudo users):\n"
            for command, description in all_commands:
                if command in ["/start", "/function"]:
                    response += f"{command} - {description}\n"

        await event.respond(response.strip())

    # Keep the bot running
    try:
        await asyncio.Event().wait()  # Wait indefinitely
    except (KeyboardInterrupt, SystemExit):
        print("Shutting down...")
        for client, _ in reporting_clients:
            await client.disconnect()
        await bot.disconnect()

# Run the bot
if __name__ == "__main__":
    print("Starting the bot...")
    asyncio.run(main())
    print("Bot has stopped.")
