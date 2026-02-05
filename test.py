#!/usr/bin/env python3
"""Test script to verify the sync setup is working properly"""
import os
import sys
from pathlib import Path

# Add the current directory to the path
current_dir = Path(__file__).parent
sys.path.insert(0, str(current_dir))

# Test imports
try:
    import requests
    import icalendar
    from dotenv import load_dotenv
    print("✅ All Python dependencies available")
except ImportError as e:
    print(f"❌ Missing dependency: {e}")
    sys.exit(1)

# Test environment
try:
    load_dotenv()
    if os.getenv('NOTIFICATION_NUMBER'):
        print("✅ NOTIFICATION_NUMBER configured")
    else:
        print("⚠️  NOTIFICATION_NUMBER not set")
        
    if os.getenv('WYZE_EMAIL') and os.getenv('WYZE_PASSWORD') and os.getenv('WYZE_KEY_ID') and os.getenv('WYZE_API_KEY'):
        print("✅ Wyze API credentials configured")
    else:
        print("❌ Missing Wyze API credentials")
        sys.exit(1)
        
    print("✅ Environment setup complete")
except Exception as e:
    print(f"❌ Environment error: {e}")
    sys.exit(1)

print("✅ All tests passed - setup is ready!")