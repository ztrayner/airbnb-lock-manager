#!/usr/bin/env python3
"""
WhatsApp notifications for Airbnb-Wyze lock changes

Uses OpenClaw CLI to send messages via WhatsApp.
This works when running via OpenClaw cron or manually.
"""

import os
import subprocess
import sys

def send_notification(message: str):
    """
    Send WhatsApp notification using OpenClaw CLI
    
    This function is called by sync.py when:
    - New booking codes are created
    - Bookings are cancelled
    - Dates are extended/modified
    - Old codes are cleaned up
    
    Requires:
    - NOTIFICATION_NUMBER env var set
    - OpenClaw CLI installed and authenticated
    
    Example messages:
    - "🔑 New lock code for GuestName\nCode: 6354\nDates: 2026-02-01 to 2026-04-16\nType: 📱 Phone-based"
    - "🔑 New lock code for GuestName\nCode: 6454\nDates: 2026-04-16 to 2026-04-17\nType: ⚠️ GENERATED (notify guest!)"
    """
    
    phone_number = os.getenv('NOTIFICATION_NUMBER', '')
    if not phone_number:
        print(f"📱 No NOTIFICATION_NUMBER set, logging only:")
        print(f"   {message}")
        return
    
    # Use OpenClaw CLI to send message
    try:
        # Ensure phone number has + prefix
        if not phone_number.startswith('+'):
            phone_number = '+' + phone_number
        
        # Build the command
        cmd = [
            'openclaw', 'message', 'send',
            '--channel', 'whatsapp',
            '--target', phone_number,
            '--message', message
        ]
        
        # Run the command
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if result.returncode == 0:
            print(f"📱 WhatsApp notification sent to {phone_number}")
        else:
            print(f"⚠️  Failed to send WhatsApp: {result.stderr}")
            print(f"   Message: {message[:80]}...")
            
    except FileNotFoundError:
        # openclaw CLI not found
        print(f"📱 openclaw CLI not found, logging message:")
        print(f"   To: {phone_number}")
        print(f"   {message}")
        
    except subprocess.TimeoutExpired:
        print(f"⚠️  WhatsApp send timed out")
        
    except Exception as e:
        print(f"⚠️  WhatsApp send error: {e}")
        print(f"   Message: {message[:80]}...")


if __name__ == "__main__":
    # Test the notification
    send_notification("🔑 Test notification from Airbnb-Wyze Lock Sync")
