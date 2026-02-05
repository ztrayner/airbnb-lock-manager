#!/bin/bash
# Setup OpenClaw cron job for 15-minute Airbnb-Wyze sync
# Only run this ONCE - running multiple times will create duplicate jobs

JOB_NAME="airbnb-wyze-lock-sync"
CRON_FILE="$HOME/.openclaw/cron/jobs.json"

# Check if job already exists
if [ -f "$CRON_FILE" ]; then
    if grep -q "\"name\": \"$JOB_NAME\"" "$CRON_FILE" 2>/dev/null; then
        echo "⚠️  Cron job '$JOB_NAME' already exists!"
        echo "   If you need to recreate it, first remove the existing job from OpenClaw dashboard."
        echo "   Or manually edit: $CRON_FILE"
        exit 1
    fi
fi

echo "Creating OpenClaw cron job for Airbnb-Wyze lock sync..."

cat > /tmp/airbnb-job.json << 'JOBEOF'
{
  "name": "airbnb-wyze-lock-sync",
  "description": "Airbnb lock sync every 15 minutes with phone-based codes",
  "schedule": {
    "kind": "cron",
    "expr": "*/15 * * * *",
    "tz": "America/Chicago"
  },
  "sessionTarget": "isolated",
  "payload": {
    "kind": "agentTurn",
    "message": "cd $PWD && . venv/bin/activate && python3 sync.py"
  },
  "enabled": true
}
JOBEOF

# Install via openclaw CLI
if command -v openclaw &> /dev/null; then
    openclaw cron add --file /tmp/airbnb-job.json
    echo "✅ Cron job added! Runs every 15 minutes."
    echo ""
    echo "To verify it's working:"
    echo "  openclaw cron list"
else
    echo "❌ OpenClaw CLI not found. Please install it first."
    exit 1
fi
