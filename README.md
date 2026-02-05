# Airbnb-Wyze Lock Sync

Complete stateful sync that handles:
- ✅ **New bookings** - Creates lock codes automatically
- ✅ **Cancellations** - Removes codes immediately  
- ✅ **Extensions** - Updates codes when guests extend stays
- ✅ **Date changes** - Handles rescheduling
- ✅ **Phone-based codes** - Uses last 4 digits of guest phone from iCal
- ✅ **Wyze API integration** - Actually sets codes on your lock

## How It Works

```
Airbnb iCal Feed (every 15 min via OpenClaw)
      ↓
Extract: Guest name, dates, phone last 4
      ↓
Detect changes (new/cancelled/extended/modified)
      ↓
Create/Update/Remove Wyze Lock Codes
      ↓
Code activates 5 min before check-in
Code expires 2 hours after check-out
```

## File Structure
```
├── sync.py              # Main automation script
├── .env                 # Your credentials (gitignored - never commit!)
├── .env.example         # Template for .env
├── .gitignore           # Ensures .env is never committed
├── requirements.txt     # Dependencies
├── setup-openclaw-cron.sh  # Cron setup script
├── venv/               # Python virtual environment
└── README.md           # This file
```

## Quick Start

### 1. Install dependencies
```bash
cd airbnb-lock-manager
python3 -m venv venv
venv/bin/pip install -r requirements.txt
```

### 2. Configure credentials (.env file)
```bash
cp .env.example .env
nano .env  # Edit with your actual credentials
```

**Required in .env:**
```env
# Wyze API Credentials (get from https://developer-api.wyze.com/)
WYZE_EMAIL=your_email@example.com
WYZE_PASSWORD=your_wyze_password
WYZE_API_KEY=your_api_key_here
WYZE_KEY_ID=your_key_id_here

# Wyze Lock Settings (find in Wyze app → Lock → Settings → Device Info)
WYZE_DEVICE_MAC=YD.LO1.xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
WYZE_DEVICE_NAME=Front Door

# Airbnb iCal URL (Host Dashboard → Calendar → Export Calendar)
AIRBNB_ICAL_URL=https://www.airbnb.com/calendar/ical/YOUR-LISTING.ics?t=YOUR_TOKEN
```

**Optional in .env:**
```env
# Timezone (where the lock is located - important for DST!)
TIMEZONE=America/Chicago

# Code timing (defaults shown)
CODE_ACTIVATION_BUFFER_MINUTES=5     # Code works 5 min before check-in
CODE_EXPIRATION_BUFFER_MINUTES=15    # Code works 15 min after check-out

# Check-in/Check-out times (since iCal only has dates)
CHECK_IN_TIME=16:00                  # 4:00 PM
CHECK_OUT_TIME=11:00                 # 11:00 AM

# Notifications (optional)
NOTIFICATION_NUMBER=1234567890
```

### 3. Test
```bash
venv/bin/python sync.py
```

### 4. Enable auto-run (every 15 minutes)
```bash
./setup-openclaw-cron.sh
```

## How Lock Codes Work

### Phone-Based Codes
The script extracts the guest's phone number from the Airbnb iCal:
```
DESCRIPTION:...
Phone Number (Last 4 Digits): 6354
```

- **If phone found**: Lock code = last 4 digits (e.g., `6354`)
- **If no phone**: Falls back to generated 4-digit code

### Code Timing
- **Activates**: Check-in day at 4:00 PM - 5 minutes buffer
- **Expires**: Check-out day at 11:00 AM + 15 minutes buffer

### Code Names in Wyze App
Each code is named for easy identification:
- Format: `Guest_{CODE}` (e.g., `Guest_6354`)
- This helps you identify guest codes vs. your own codes

### Timezone Support
The script uses the timezone where your lock is located (default: `America/Chicago`):
- Handles Daylight Saving Time (DST) automatically
- Check-in/out times are applied in the lock's local timezone
- Configure with `TIMEZONE` env var (e.g., `America/New_York`, `America/Denver`)

### Change Detection
The script maintains state and detects:
- 🗑️ **Cancellations** - removes codes immediately
- ➕ **New bookings** - adds new codes
- ✏️ **Extensions** - updates checkout date
- 📅 **Date changes** - reschedules access

## Security Notes

- **Never commit `.env`** - it's in `.gitignore` by default
- **Keep `.env` permissions restricted** (`chmod 600 .env`)
- **API keys expire** - Wyze API keys expire after 1 year

## Troubleshooting

### "Missing required environment variables"
Check that your `.env` file has all required values:
```bash
venv/bin/python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('WYZE_EMAIL:', os.getenv('WYZE_EMAIL'))"
```

### "Wyze authentication failed"
- Check your API key hasn't expired
- Verify email/password are correct

### Check logs
```bash
tail -f sync.log
```

## Manual Run

```bash
venv/bin/python sync.py
```

## Dry Run

```bash
venv/bin/python sync.py --dry-run
```
