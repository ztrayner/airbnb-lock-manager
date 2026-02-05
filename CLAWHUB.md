# Airbnb-Wyze Lock Automation

**Category:** Smart Home Automation  
**Author:** ztrayner  
**Version:** 1.0.0

Automatically sync Airbnb bookings with Wyze lock access codes. Creates temporary access codes for guests using their phone number's last 4 digits.

## What It Does

- 🏠 **Monitors** your Airbnb calendar every 15 minutes via OpenClaw
- 🔑 **Creates** temporary lock codes when guests book
- 🗑️ **Removes** codes when bookings are cancelled
- ✏️ **Updates** codes when guests extend or change dates
- 📱 **Uses** guest's phone last 4 digits as the access code
- ⏰ **Activates** 5 minutes before check-in, expires 15 minutes after check-out
- 🏷️ **Names codes** as `Guest_{CODE}` (e.g., `Guest_6354`)
- 🌎 **Timezone-aware** - handles DST for lock location

## Quick Start

```bash
# 1. Clone/configure
cd airbnb-lock-manager
cp .env.example .env
nano .env  # Add your credentials

# 2. Install
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. Test
venv/bin/python sync.py

# 4. Enable auto-run
./setup-openclaw-cron.sh
```

## Required Setup

### 1. Wyze API Key
Visit https://developer-api.wyze.com/ to generate:
- API Key
- Key ID

### 2. Wyze Lock MAC Address
Find in Wyze app → Lock → Settings → Device Info

### 3. Airbnb iCal URL
Host Dashboard → Calendar → Export Calendar → Copy iCal URL

## Configuration (.env file)

```env
# Required
WYZE_EMAIL=your_email@example.com
WYZE_PASSWORD=your_password
WYZE_API_KEY=your_api_key
WYZE_KEY_ID=your_key_id
WYZE_DEVICE_MAC=YD.LO1.xxxxxxxx
WYZE_DEVICE_NAME=Front Door
AIRBNB_ICAL_URL=https://www.airbnb.com/calendar/ical/...

# Optional
CODE_ACTIVATION_BUFFER_MINUTES=5
CODE_EXPIRATION_BUFFER_MINUTES=15
CHECK_IN_TIME=16:00
CHECK_OUT_TIME=11:00
NOTIFICATION_NUMBER=1234567890
```

## How It Works

```
Airbnb iCal Feed
      ↓
  [sync.py]  ← Runs every 15 min via OpenClaw
      ↓
Detects Changes (new/cancelled/extended)
      ↓
Creates/Updates/Removes Wyze Lock Codes
      ↓
Uses phone last 4 as code (e.g., 6354)
```

## OpenClaw Integration

This automation runs via OpenClaw's cron system:

```json
{
  "name": "airbnb-wyze-lock-sync",
  "schedule": "*/15 * * * *",
  "action": "python sync.py"
}
```

Run `./setup-openclaw-cron.sh` to install.

## Dependencies

- Python 3.10+
- wyze-sdk
- icalendar
- python-dotenv
- requests

## Files

- `sync.py` - Main automation script
- `.env` - Your credentials (gitignored - create from .env.example)
- `.env.example` - Template showing required variables
- `setup-openclaw-cron.sh` - One-click cron setup
