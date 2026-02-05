#!/usr/bin/env python3
"""
Airbnb-Wyze Lock Sync - Complete
One directory, one project, all edge cases

Handles: extensions, cancellations, date changes, sync at 15-min intervals
"""

import argparse
import json
import logging
import logging.handlers
import os
import re
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# Fix for Python 3.12+ distutils removal (wyze-sdk dependency requires distutils)
# This hack may need updates for future Python versions
try:
    import distutils
except ImportError:
    import setuptools
    sys.modules['distutils'] = setuptools._distutils

try:
    import icalendar
    import requests
    from dotenv import load_dotenv
except ImportError:
    import subprocess
    subprocess.run(["pip", "install", "icalendar", "requests", "python-dotenv"])
    import icalendar
    import requests
    from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class AirbnbWyzeSync:
    def __init__(self, dry_run: bool = False):
        self.base_dir = Path(__file__).parent
        self.state_file = self.base_dir / "bookings_state.json"
        self.log_file = self.base_dir / "sync.log"
        self.dry_run = dry_run
        
        self.config = self._load_config()
        self.lock_api = None  # Lazy initialization
        
        self._setup_logging()
        self.ensure_directories()
        
        if self.dry_run:
            self.log("🧪 DRY RUN MODE - No changes will be made to Wyze lock")
    
    def _setup_logging(self):
        """Setup rotating file logger (1MB max, 3 backups)"""
        self.logger = logging.getLogger('airbnb-wyze-sync')
        self.logger.setLevel(logging.INFO)
        
        # Avoid adding duplicate handlers if called multiple times
        if not self.logger.handlers:
            # File handler with rotation
            file_handler = logging.handlers.RotatingFileHandler(
                self.log_file,
                maxBytes=1_000_000,  # 1MB
                backupCount=3,
                encoding='utf-8'
            )
            file_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
            self.logger.addHandler(file_handler)
            
            # Also log to stdout
            console_handler = logging.StreamHandler()
            console_handler.setFormatter(logging.Formatter('%(asctime)s - %(message)s', datefmt='%Y-%m-%d %H:%M:%S'))
            self.logger.addHandler(console_handler)
    
    def get_lock_api(self):
        """Lazy initialization of Wyze API"""
        if self.lock_api is None:
            self.lock_api = WyzeLockAPI(self.config)
        return self.lock_api
    
    def send_whatsapp_notification(self, message: str):
        """Send WhatsApp notification when codes change"""
        notification_number = os.getenv('NOTIFICATION_NUMBER', '')
        if not notification_number:
            return
        
        # Use notifications.py module (handles OpenClaw integration)
        try:
            from notifications import send_notification
            send_notification(message)
            self.log(f"📱 Notification sent")
        except Exception as e:
            # Fallback: log the message so it's visible in OpenClaw logs
            self.log(f"📱 Notification: {message[:80]}...")
            if "No module named" not in str(e):
                self.log(f"   (Error: {e})")
    
    def ensure_directories(self):
        """Setup required directories"""
        self.log_file.parent.mkdir(exist_ok=True)
    
    def log(self, message: str):
        """Log sync events using rotating logger"""
        self.logger.info(message)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load all configuration from environment (.env file)"""
        config = {
            # Wyze API Credentials
            "wyze_email": os.getenv('WYZE_EMAIL', ''),
            "wyze_password": os.getenv('WYZE_PASSWORD', ''),
            "wyze_api_key": os.getenv('WYZE_API_KEY', ''),
            "wyze_key_id": os.getenv('WYZE_KEY_ID', ''),
            
            # Wyze Lock Settings
            "lock_device_mac": os.getenv('WYZE_DEVICE_MAC', ''),
            "device_name": os.getenv('WYZE_DEVICE_NAME', 'Front Door'),
            
            # Airbnb iCal
            "ical_url": os.getenv('AIRBNB_ICAL_URL', ''),
            
            # Code Timing (buffer before check-in, after check-out)
            "activation_buffer_minutes": int(os.getenv('CODE_ACTIVATION_BUFFER_MINUTES', '5')),
            "expiration_buffer_minutes": int(os.getenv('CODE_EXPIRATION_BUFFER_MINUTES', '15')),
            
            # Check-in/out times (Airbnb standard if not in iCal)
            "check_in_time": os.getenv('CHECK_IN_TIME', '16:00'),  # 4 PM default
            "check_out_time": os.getenv('CHECK_OUT_TIME', '11:00'),  # 11 AM default
            
            # Timezone (for the lock location)
            "timezone": os.getenv('TIMEZONE', 'America/Chicago'),
            
            # API Key Expiration (for renewal reminders)
            # Format: YYYY-MM-DD or MM-DD-YYYY HH:MM:SS
            "api_key_expires": os.getenv('WYZE_API_KEY_EXPIRES', ''),
        }
        
        # Validate required config
        missing = []
        if not config["wyze_email"]:
            missing.append("WYZE_EMAIL")
        if not config["wyze_password"]:
            missing.append("WYZE_PASSWORD")
        if not config["ical_url"]:
            missing.append("AIRBNB_ICAL_URL")
        
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
        
        return config
    
    def check_api_key_expiration(self):
        """Check if Wyze API key is expiring soon and send warnings"""
        expires_str = self.config.get("api_key_expires", "")
        if not expires_str:
            return
        
        try:
            # Parse expiration date (try common formats)
            expires_dt = None
            formats = [
                "%Y-%m-%d",           # 2027-02-04
                "%Y-%m-%d %H:%M:%S",  # 2027-02-04 01:41:34
                "%m-%d-%Y",           # 02-04-2027
                "%m-%d-%Y %H:%M:%S",  # 02-04-2027 01:41:34
            ]
            
            for fmt in formats:
                try:
                    expires_dt = datetime.strptime(expires_str.strip(), fmt)
                    break
                except ValueError:
                    continue
            
            if not expires_dt:
                self.log(f"⚠️  Could not parse API key expiration date: {expires_str}")
                return
            
            # Make timezone-aware
            tz_name = self.config.get('timezone', 'America/Chicago')
            try:
                import pytz
                tz = pytz.timezone(tz_name)
                expires_dt = tz.localize(expires_dt)
                now = datetime.now(tz)
            except Exception:
                now = datetime.now()
            
            # Calculate time until expiration
            time_until = expires_dt - now
            days_until = time_until.days
            
            # Load state to track which warnings have been sent
            state = self.load_bookings_state()
            api_warnings = state.get("api_key_warnings", {})
            
            # Determine warning level and message
            warning_sent = False
            
            if days_until < 0:
                # EXPIRED
                if not api_warnings.get("expired"):
                    self.send_whatsapp_notification(
                        f"🚨 URGENT: Wyze API key has EXPIRED!\n"
                        f"Expired: {expires_dt.strftime('%Y-%m-%d')}\n"
                        f"Lock codes will NOT sync until renewed.\n"
                        f"Generate new key at: https://developer-api.wyze.com/"
                    )
                    api_warnings["expired"] = True
                    warning_sent = True
                    self.log("🚨 API key EXPIRED - notification sent")
                    
            elif days_until <= 1:
                # 1 day warning
                if not api_warnings.get("1day"):
                    self.send_whatsapp_notification(
                        f"⚠️ WARNING: Wyze API key expires in {days_until} day(s)!\n"
                        f"Expires: {expires_dt.strftime('%Y-%m-%d %H:%M')}\n"
                        f"Renew at: https://developer-api.wyze.com/"
                    )
                    api_warnings["1day"] = True
                    warning_sent = True
                    self.log(f"⚠️  API key expires in {days_until} day(s) - notification sent")
                    
            elif days_until <= 7:
                # 1 week warning
                if not api_warnings.get("1week"):
                    self.send_whatsapp_notification(
                        f"⏰ Reminder: Wyze API key expires in {days_until} days\n"
                        f"Expires: {expires_dt.strftime('%Y-%m-%d')}\n"
                        f"Renew at: https://developer-api.wyze.com/"
                    )
                    api_warnings["1week"] = True
                    warning_sent = True
                    self.log(f"⏰ API key expires in {days_until} days - notification sent")
                    
            elif days_until <= 30:
                # 1 month warning
                if not api_warnings.get("1month"):
                    self.send_whatsapp_notification(
                        f"📅 Wyze API key expires in {days_until} days\n"
                        f"Expires: {expires_dt.strftime('%Y-%m-%d')}\n"
                        f"Mark your calendar to renew at: https://developer-api.wyze.com/"
                    )
                    api_warnings["1month"] = True
                    warning_sent = True
                    self.log(f"📅 API key expires in {days_until} days - notification sent")
            
            # Save warning state if we sent something
            if warning_sent:
                state["api_key_warnings"] = api_warnings
                self.save_bookings_state(state)
                
        except Exception as e:
            self.log(f"⚠️  Error checking API key expiration: {e}")
    
    def load_bookings_state(self) -> Dict[str, Any]:
        """Load previous bookings state for change detection"""
        if self.state_file.exists():
            try:
                with open(self.state_file) as f:
                    return json.load(f)
            except json.JSONDecodeError:
                self.log("⚠️  Corrupted state file, using empty state")
        return {"bookings": {}, "last_sync": None}
    
    def save_bookings_state(self, state: Dict[str, Any]):
        """Save current bookings state for diffing"""
        state["last_sync"] = datetime.now().isoformat()
        with open(self.state_file, 'w') as f:
            json.dump(state, f, indent=2)
    
    def fetch_current_bookings(self) -> Dict[str, Dict[str, Any]]:
        """Fetch current bookings from Airbnb"""
        if not self.config["ical_url"]:
            self.log("❌ Missing AIRBNB_ICAL_URL - set in .env file")
            return {}
        
        try:
            response = requests.get(self.config["ical_url"], timeout=30)
            response.raise_for_status()
        except Exception as e:
            self.log(f"❌ Failed to fetch iCal: {e}")
            return {}
        
        try:
            return self._parse_ical(response.text)
        except Exception as e:
            self.log(f"❌ Failed to parse iCal: {e}")
            return {}
    
    def _extract_phone_last4(self, description: str) -> Optional[str]:
        """Extract last 4 digits of phone number from iCal DESCRIPTION"""
        if not description:
            return None
        # Look for "Phone Number (Last 4 Digits): XXXX"
        match = re.search(r'Phone Number \(Last 4 Digits\):\s*(\d{4})', str(description))
        if match:
            return match.group(1)
        return None
    
    def _extract_reservation_id(self, description: str) -> Optional[str]:
        """Extract reservation ID from iCal DESCRIPTION"""
        if not description:
            return None
        # Look for reservation ID in URL like: /details/HMKHCAK3M3
        match = re.search(r'/details/([A-Z0-9]+)', str(description))
        if match:
            return match.group(1)
        return None
    
    def _parse_ical(self, ical_data: str) -> Dict[str, Dict[str, Any]]:
        """Parse iCal data into structured bookings"""
        cal = icalendar.Calendar.from_ical(ical_data)
        bookings = {}
        
        for component in cal.walk():
            if component.name == "VEVENT":
                try:
                    # Get summary FIRST to check if this is a blocked date
                    summary = str(component.get("SUMMARY", "Guest"))
                    
                    # Skip blocked dates and non-reservation events EARLY
                    # These include "Not available", "Airbnb (Not available)", etc.
                    summary_lower = summary.lower()
                    if ("not available" in summary_lower or 
                        "blocked" in summary_lower or
                        summary_lower.strip() == "airbnb" or
                        summary_lower.startswith("airbnb (")):
                        continue
                    
                    booking_id = str(component.get("UID", "unknown"))
                    start = component.get("DTSTART").dt
                    end = component.get("DTEND").dt
                    
                    # Clean guest name (after we know it's a real reservation)
                    guest = summary.split(":")[-1].split("(")[0].strip() or "Guest"
                    
                    # Extract info from description
                    description = str(component.get("DESCRIPTION", ""))
                    phone_last4 = self._extract_phone_last4(description)
                    reservation_id = self._extract_reservation_id(description)
                    
                    # Use phone last 4 as code, fallback to generated code
                    # Note: We don't log here to avoid spam - logging happens in process_changes
                    if phone_last4:
                        code = phone_last4
                    else:
                        # Generate unique code as fallback
                        code_seed = f"{booking_id}{start}{guest}"                    
                        code = hashlib.md5(code_seed.encode()).hexdigest()[:4]
                        code = str(int(code, 16))[:4]  # Ensure numeric
                    
                    booking = {
                        "guest_name": guest,
                        "reservation_id": reservation_id,
                        "start": start.isoformat(),
                        "end": end.isoformat(),
                        "code": code,
                        "phone_last4": phone_last4,
                        "created_at": datetime.now().isoformat()
                    }
                    
                    bookings[booking_id] = booking
                    
                except Exception as e:
                    self.log(f"⚠️  Skipping malformed booking: {e}")
        
        return bookings
    
    def detect_changes(self, previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, List[Dict[str, Any]]]:
        """
        Detect all booking changes with precision
        
        Returns changes dict with:
        - cancellations: removed bookings
        - new_bookings: fresh bookings
        - extensions: dates extended
        - date_changes: date modifications (earlier or different dates)
        """
        prev_ids = set(previous.get("bookings", {}).keys())
        curr_ids = set(current.keys())
        
        changes = {
            "cancellations": [],
            "new_bookings": [],
            "extensions": [],
            "date_changes": []
        }
        
        # Cancellations
        for booking_id in prev_ids - curr_ids:
            changes["cancellations"].append(previous["bookings"][booking_id])
            self.log(f"🗑️ Cancellation: {previous['bookings'][booking_id]['guest_name']}")
        
        # New bookings
        for booking_id in curr_ids - prev_ids:
            changes["new_bookings"].append(current[booking_id])
            self.log(f"➕ New booking: {current[booking_id]['guest_name']} ({current[booking_id]['start']})")
        
        # Changes/existing bookings
        for booking_id in curr_ids & prev_ids:
            prev_booking = previous["bookings"][booking_id]
            curr_booking = current[booking_id]
            
            if (prev_booking["start"] != curr_booking["start"] or 
                prev_booking["end"] != curr_booking["end"]):
                
                prev_end = datetime.fromisoformat(prev_booking["end"])
                curr_end = datetime.fromisoformat(curr_booking["end"])
                
                if curr_end > prev_end:
                    changes["extensions"].append({"before": prev_booking, "after": curr_booking})
                    self.log(f"✏️ Extension: {curr_booking['guest_name']} {prev_end.strftime('%m/%d')} → {curr_end.strftime('%m/%d')}")
                else:
                    changes["date_changes"].append({"before": prev_booking, "after": curr_booking})
                    self.log(f"✏️ Date change: {curr_booking['guest_name']} modified dates")
        
        return changes
    
    def process_changes(self, changes: Dict[str, List[Dict[str, Any]]]):
        """Apply detected changes to Wyze lock"""
        total_changes = sum(len(v) for v in changes.values())
        
        if total_changes == 0:
            return
        
        self.log(f"🔄 Processing {total_changes} changes...")
        
        # In dry-run mode, just log what would happen
        if self.dry_run:
            for booking in changes["cancellations"]:
                self.log(f"   [DRY RUN] Would remove code {booking['code']} for {booking['guest_name']}")
            for booking in changes["new_bookings"]:
                is_phone_based = booking.get("phone_last4") is not None
                code_type = "phone-based" if is_phone_based else "generated"
                self.log(f"   [DRY RUN] Would add {code_type} code {booking['code']} for {booking['guest_name']}")
            for change in (changes["extensions"] + changes["date_changes"]):
                self.log(f"   [DRY RUN] Would update code {change['after']['code']} for {change['after']['guest_name']}")
            return
        
        # Initialize Wyze API only when needed
        try:
            lock = self.get_lock_api()
        except Exception as e:
            self.log(f"❌ Cannot connect to Wyze lock: {e}")
            self.log("   Codes NOT updated. Fix Wyze credentials in .env file")
            return
        
        # Handle cancellations first
        for booking in changes["cancellations"]:
            lock.remove_code(booking["code"], booking["guest_name"])
            self.send_whatsapp_notification(f"🗑️ Cancelled: Removed code {booking['code']} for {booking['guest_name']}")
        
        # Handle new bookings
        for booking in changes["new_bookings"]:
            try:
                # Log the code type for new bookings
                is_phone_based = booking.get("phone_last4") is not None
                if is_phone_based:
                    self.log(f"📱 Using phone last 4 for {booking['guest_name']}: {booking['code']}")
                else:
                    self.log(f"⚠️  No phone for {booking['guest_name']}, using generated code: {booking['code']}")
                
                lock.add_code(
                    booking["code"], 
                    booking["guest_name"], 
                    booking.get("reservation_id"),
                    booking["start"], 
                    booking["end"]
                )
                
                # Send WhatsApp notification
                code_type = "📱 Phone-based" if is_phone_based else "⚠️ GENERATED (notify guest!)"
                dates = f"{booking['start'][:10]} to {booking['end'][:10]}"
                message = f"🔑 New lock code for {booking['guest_name']}\nCode: {booking['code']}\nDates: {dates}\nType: {code_type}"
                self.send_whatsapp_notification(message)
                
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    self.log(f"⚠️  Code {booking['code']} already exists, skipping")
                else:
                    raise
        
        # Handle extensions/date changes
        for change in (changes["extensions"] + changes["date_changes"]):
            # Remove old code
            lock.remove_code(change["before"]["code"], change["before"]["guest_name"])
            
            # Add with new dates
            try:
                lock.add_code(
                    change["after"]["code"],
                    change["after"]["guest_name"], 
                    change["after"].get("reservation_id"),
                    change["after"]["start"],
                    change["after"]["end"]
                )
                
                # Determine if extension or change
                is_extension = change["after"]["end"] > change["before"]["end"]
                change_type = "Extended" if is_extension else "Modified"
                
                old_dates = f"{change['before']['start'][:10]} to {change['before']['end'][:10]}"
                new_dates = f"{change['after']['start'][:10]} to {change['after']['end'][:10]}"
                message = f"✏️ {change_type}: {change['after']['guest_name']}\nCode: {change['after']['code']}\n{old_dates} → {new_dates}"
                self.send_whatsapp_notification(message)
                
            except Exception as e:
                if "duplicate" in str(e).lower() or "already exists" in str(e).lower():
                    self.log(f"⚠️  Code {change['after']['code']} already exists, skipping")
                else:
                    raise
    
    def cleanup_old_codes(self):
        """Remove Wyze codes for bookings that ended more than 2 weeks ago"""
            
        try:
            lock = self.get_lock_api()
            if lock is None:
                return
            
            # Get all current access codes from Wyze
            # Note: Method is get_keys(), returns LockKey objects
            codes = lock.client.locks.get_keys(
                device_mac=lock.lock_device.mac
            )
            
            cutoff_date = datetime.now() - timedelta(days=14)  # 2 weeks ago
            removed_count = 0
            
            for code in codes:
                # Check if this is one of our guest codes (starts with "Guest_")
                if code.name and code.name.startswith("Guest_"):
                    # Check if code has expired and is old
                    if code.permission and code.permission.end:
                        end_time = code.permission.end
                        if isinstance(end_time, str):
                            end_time = datetime.fromisoformat(end_time.replace('Z', '+00:00'))
                        
                        if end_time < cutoff_date:
                            if self.dry_run:
                                self.log(f"   [DRY RUN] Would remove old code '{code.name}' (expired {end_time.strftime('%Y-%m-%d')})")
                                removed_count += 1
                                continue

                            self.log(f"🧹 Removing old code '{code.name}' (expired {end_time.strftime('%Y-%m-%d')})")
                            try:
                                lock.client.locks.delete_access_code(
                                    device_mac=lock.lock_device.mac,
                                    device_model=lock.lock_device.product.model,
                                    access_code_id=code.id
                                )
                                removed_count += 1
                            except Exception as e:
                                self.log(f"⚠️  Failed to remove old code '{code.name}': {e}")
            
            if removed_count > 0:
                if self.dry_run:
                    self.log(f"   [DRY RUN] Would have cleaned up {removed_count} old codes")
                else:
                    self.log(f"🧹 Cleaned up {removed_count} old codes")
                    self.send_whatsapp_notification(f"🧹 Cleaned up {removed_count} old lock codes from past guests")
            else:
                self.log("✅ No old codes to clean up")
                
        except Exception as e:
            self.log(f"⚠️  Cleanup failed: {e}")
    
    def sync(self):
        """Main sync function - runs every 15 minutes"""
        # Check API key expiration first
        self.check_api_key_expiration()
        
        state = self.load_bookings_state()
        previous_bookings = state.get("bookings", {})
        
        self.log("🔄 Starting booking sync...")
        
        current_bookings = self.fetch_current_bookings()
        if not current_bookings:
            return
        
        changes = self.detect_changes(state, current_bookings)
        
        if not any(changes.values()):
            self.log("✅ No booking changes detected")
        else:
            self.process_changes(changes)
            
            summary = f"Changes: {len(changes['cancellations'])}✂️  {len(changes['new_bookings'])}➕ {len(changes['extensions'])}✏️ {len(changes['date_changes'])}📅"
            self.log(summary)
        
        # Clean up old codes (runs every time, but only removes codes > 2 weeks old)
        self.cleanup_old_codes()
        
        # Save updated state
        new_state = {
            "bookings": current_bookings,
            "last_sync": datetime.now().isoformat()
        }
        self.save_bookings_state(new_state)


class WyzeLockAPI:
    """Wyze lock API integration using wyze-sdk"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.client = None
        self.lock_device = None
        self._authenticate()
    
    def _authenticate(self):
        """Authenticate with Wyze API using API Key (required since July 2023)"""
        try:
            from wyze_sdk import Client
            from wyze_sdk.errors import WyzeApiError
            
            email = self.config.get('wyze_email')
            password = self.config.get('wyze_password')
            api_key = self.config.get('wyze_api_key')
            key_id = self.config.get('wyze_key_id')
            
            if not email or not password:
                raise ValueError("Wyze email and password required in config")
            
            # API Key authentication (required as of July 2023)
            if api_key and api_key != "YOUR_WYZE_API_KEY" and key_id and key_id != "YOUR_WYZE_KEY_ID":
                # Create client with API key
                self.client = Client()
                self.client.login(
                    email=email, 
                    password=password,
                    api_key=api_key,
                    key_id=key_id
                )
                self.log("✅ Authenticated with Wyze (API Key)")
            else:
                # Fallback to legacy auth (will fail for most accounts now)
                self.log("⚠️  WARNING: Using legacy auth. Get API key from https://support.wyze.com/hc/en-us/articles/16129834216731")
                self.client = Client()
                self.client.login(email=email, password=password)
                self.log("✅ Authenticated with Wyze (Legacy)")
            
            # Find the lock device
            self._find_lock_device()
            
        except ImportError:
            raise ImportError("wyze-sdk not installed. Run: pip install wyze-sdk")
        except Exception as e:
            raise RuntimeError(f"Wyze authentication failed: {e}")
    
    def _find_lock_device(self):
        """Find the lock device by MAC or name"""
        from wyze_sdk.errors import WyzeApiError
        
        target_mac = self.config.get('lock_device_mac', '').lower()
        target_name = self.config.get('device_name', '')
        
        try:
            devices = self.client.devices_list()
            for device in devices:
                if device.product.model == 'YD.LO1':  # Wyze Lock model
                    device_mac = device.mac.lower()
                    if target_mac and target_mac in device_mac:
                        self.lock_device = device
                        self.log(f"🔒 Found lock by MAC: {device.nickname}")
                        return
                    elif target_name and target_name.lower() in device.nickname.lower():
                        self.lock_device = device
                        self.log(f"🔒 Found lock by name: {device.nickname}")
                        return
            
            if not self.lock_device:
                raise ValueError(f"Lock not found. Check device_mac or device_name in config.")
                
        except WyzeApiError as e:
            raise RuntimeError(f"Failed to list devices: {e}")
    
    def add_code(self, code: str, guest_name: str, reservation_id: Optional[str], start_iso: str, end_iso: str):
        """Add temporary access code to Wyze lock with timezone support"""
        from wyze_sdk.errors import WyzeApiError
        
        # Get timezone setting
        tz_name = self.config.get('timezone', 'America/Chicago')
        try:
            import pytz
            tz = pytz.timezone(tz_name)
        except ImportError:
            self.log("⚠️  pytz not installed, using UTC. Install with: pip install pytz")
            tz = None
        
        # Parse dates from iCal (these are dates only, no time)
        start_date = datetime.fromisoformat(start_iso).date()
        end_date = datetime.fromisoformat(end_iso).date()
        
        # Get check-in/check-out times from config
        check_in_time = self.config.get('check_in_time', '16:00')
        check_out_time = self.config.get('check_out_time', '11:00')
        
        # Parse times
        check_in_hour, check_in_min = map(int, check_in_time.split(':'))
        check_out_hour, check_out_min = map(int, check_out_time.split(':'))
        
        # Combine date + time, then apply timezone
        check_in_dt = datetime(start_date.year, start_date.month, start_date.day, 
                               check_in_hour, check_in_min)
        check_out_dt = datetime(end_date.year, end_date.month, end_date.day,
                                check_out_hour, check_out_min)
        
        # Localize to lock's timezone
        if tz:
            check_in_dt = tz.localize(check_in_dt)
            check_out_dt = tz.localize(check_out_dt)
            self.log(f"   Lock timezone: {tz_name}")
        
        # Add buffers: X min before check-in, X minutes after check-out
        buffer_minutes = self.config.get('activation_buffer_minutes', 5)
        expiration_minutes = self.config.get('expiration_buffer_minutes', 15)
        active_start = check_in_dt - timedelta(minutes=buffer_minutes)
        active_end = check_out_dt + timedelta(minutes=expiration_minutes)
        
        # Log the times
        if tz:
            self.log(f"   Check-in: {check_in_dt.strftime('%Y-%m-%d %H:%M %Z')}")
            self.log(f"   Check-out: {check_out_dt.strftime('%Y-%m-%d %H:%M %Z')}")
        
        # Generate a unique access code name
        code_name = f"Guest_{code}"
        
        try:
            from wyze_sdk.models.devices.locks import LockKeyPermission, LockKeyPermissionType
            
            # Create permission with begin/end times (DURATION = temporary code)
            permission = LockKeyPermission(
                type=LockKeyPermissionType.DURATION,
                begin=active_start,
                end=active_end
            )
            
            # Create the access code using correct API signature
            self.client.locks.create_access_code(
                device_mac=self.lock_device.mac,
                access_code=code,
                name=code_name,
                permission=permission
            )
            self.log(f"🔓 Added code {code} for {guest_name}")
            self.log(f"   Active: {active_start.strftime('%m/%d %H:%M')} - {active_end.strftime('%m/%d %H:%M')}")
                
        except Exception as e:
            # Log the error but don't crash - allows debugging
            self.log(f"⚠️  Wyze API error: {e}")
            self.log(f"   Would have added code {code} for {guest_name}")
            self.log(f"   Active: {active_start.strftime('%m/%d %H:%M')} - {active_end.strftime('%m/%d %H:%M')}")
    
    def remove_code(self, code: str, guest_name: str):
        """Remove access code from Wyze lock"""
        from wyze_sdk.errors import WyzeApiError
        
        try:
            # Get all access codes for the lock
            codes = self.client.locks.get_access_codes(
                device_mac=self.lock_device.mac,
                device_model=self.lock_device.product.model
            )
            
            # Find and delete the matching code
            deleted = False
            for access_code in codes:
                if access_code.code == code:
                    self.client.locks.delete_access_code(
                        device_mac=self.lock_device.mac,
                        device_model=self.lock_device.product.model,
                        access_code_id=access_code.id
                    )
                    self.log(f"🔒 Removed code {code} for {guest_name}")
                    deleted = True
                    break
            
            if not deleted:
                self.log(f"⚠️  Code {code} not found on lock (may have expired)")
                
        except WyzeApiError as e:
            self.log(f"❌ Failed to remove code {code}: {e}")
            raise
    
    def log(self, message: str):
        """Log message (passed to main logger)"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"{timestamp} - {message}")


def main():
    """Entry point for cron or manual execution"""
    parser = argparse.ArgumentParser(
        description='Sync Airbnb bookings with Wyze lock codes',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python sync.py              # Normal sync (runs every 15 min via cron)
  python sync.py --dry-run    # Preview changes without modifying lock
        """
    )
    parser.add_argument(
        '--dry-run', '-n',
        action='store_true',
        help='Preview changes without modifying the Wyze lock'
    )
    args = parser.parse_args()
    
    try:
        sync = AirbnbWyzeSync(dry_run=args.dry_run)
        sync.sync()
    except KeyboardInterrupt:
        print("\nGracefully stopped")
    except Exception as e:
        print(f"❌ Sync failed: {e}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())