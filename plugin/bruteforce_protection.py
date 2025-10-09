# -*- coding: utf-8 -*-

##########################################################################
# OpenWebif: Brute Force Protection
##########################################################################
# Copyright (C) 2025 E2OpenPlugins
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software Foundation,
# Inc., 51 Franklin Street, Fifth Floor, Boston MA 02110-1301, USA.
##########################################################################

"""
Brute Force Protection Module

This module implements progressive delay-based protection against brute force
login attacks. It tracks failed login attempts per IP address and applies
increasing delays to slow down attackers.

Features:
- Progressive delays: Each failed attempt increases the delay
- Automatic cleanup: Old tracking data expires after 1 hour
- IP-based tracking: Separate counters for each attacker
- Configurable: Easy to adjust delay times and thresholds
"""

from __future__ import print_function
import time
import threading
import os
from datetime import datetime

# Configuration Constants
MAX_TRACKING_TIME = 3600  # 1 hour - how long to remember failed attempts
LOCKOUT_DURATION = 120    # 2 minutes - complete lockout after max attempts
MAX_FAILED_ATTEMPTS = 5   # Number of attempts before lockout
LOG_FILE = "/tmp/openwebif_brute_force.log"  # Log file location
MAX_LOG_SIZE = 1048576    # 1MB - rotate log when it exceeds this size
MAX_LOG_FILES = 3         # Keep 3 old rotated logs

# Progressive delay schedule (attempt number -> delay in seconds)
DELAY_SCHEDULE = {
    1: 0,    # First attempt: instant
    2: 2,    # Second attempt: 2 seconds
    3: 5,    # Third attempt: 5 seconds
    4: 10,   # Fourth attempt: 10 seconds
    5: 20,   # Fifth attempt: 20 seconds - last chance before lockout
}
DEFAULT_DELAY = 30  # 6+ attempts: 30 seconds (shouldn't reach here due to lockout)

# Global tracking dictionary
# Structure: {ip_address: {'attempts': int, 'first_attempt': timestamp, 'locked_until': timestamp}}
failed_attempts = {}

# Global attempt tracking (for when IPs change)
# List of tuples: [(timestamp, ip_address), ...]
global_attempts = []
GLOBAL_WINDOW = 300  # 5 minutes window for global tracking
GLOBAL_MAX_ATTEMPTS = 10  # Max attempts globally within window

lock = threading.Lock()


def rotate_log():
	"""
	Rotate log file if it exceeds MAX_LOG_SIZE.
	Keeps MAX_LOG_FILES old logs (.1, .2, .3)
	"""
	try:
		if not os.path.exists(LOG_FILE):
			return

		size = os.path.getsize(LOG_FILE)
		if size > MAX_LOG_SIZE:
			# Rotate old logs
			for i in range(MAX_LOG_FILES - 1, 0, -1):
				old_log = LOG_FILE + "." + str(i)
				new_log = LOG_FILE + "." + str(i + 1)
				if os.path.exists(old_log):
					if i + 1 > MAX_LOG_FILES:
						os.remove(old_log)
					else:
						if os.path.exists(new_log):
							os.remove(new_log)
						os.rename(old_log, new_log)

			# Move current log to .1
			if os.path.exists(LOG_FILE):
				os.rename(LOG_FILE, LOG_FILE + ".1")

			print("[OpenWebif] Brute force protection: Log rotated at %d bytes" % size)
	except Exception as e:
		# Don't let rotation failures break the protection
		print("[OpenWebif] Brute force protection: Log rotation failed: %s" % str(e))


def log_to_file(message):
	"""
	Write a log message to the brute force log file.
	Includes timestamp, automatic rotation, and ensures thread-safe writes.

	Args:
		message (str): The message to log
	"""
	try:
		# Check if rotation needed before writing
		rotate_log()

		timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
		with open(LOG_FILE, "a") as f:
			f.write("[%s] %s\n" % (timestamp, message))
	except Exception as e:
		# Don't let logging failures break the protection
		print("[OpenWebif] Brute force protection: Failed to write to log file: %s" % str(e))


def log_login_attempt(ip_address, username, success, reason=""):
    """
    Log ALL login attempts - successful, failed, blocked, etc.
    This provides a complete traffic log.

    Args:
        ip_address (str): The IP address attempting to log in
        username (str): The username attempted
        success (bool): True if login succeeded
        reason (str): Reason for failure (optional)
    """
    if success:
        msg = "LOGIN SUCCESS: IP %s, user '%s'" % (ip_address, username)
        log_to_file("[SUCCESS] %s" % msg)
    else:
        if reason:
            msg = "LOGIN FAILED: IP %s, user '%s' - %s" % (ip_address, username, reason)
        else:
            msg = "LOGIN FAILED: IP %s, user '%s'" % (ip_address, username)
        log_to_file("[FAILED] %s" % msg)


def cleanup_old_entries():
    """
    Remove old tracking entries that have expired.
    Called automatically before each login attempt check.
    """
    current_time = time.time()
    with lock:
        # Clean up per-IP tracking
        expired_ips = []
        for ip, data in failed_attempts.items():
            # Remove if tracking time expired and not currently locked out
            if 'first_attempt' in data:
                if current_time - data['first_attempt'] > MAX_TRACKING_TIME:
                    if 'locked_until' not in data or current_time > data['locked_until']:
                        expired_ips.append(ip)

        for ip in expired_ips:
            del failed_attempts[ip]
            print("[OpenWebif] Brute force protection: Cleaned up expired entry for IP %s" % ip)

        # Clean up global attempts older than window
        global global_attempts
        cutoff = current_time - GLOBAL_WINDOW
        old_count = len(global_attempts)
        global_attempts = [(ts, ip) for ts, ip in global_attempts if ts > cutoff]
        if old_count != len(global_attempts):
            print("[OpenWebif] Brute force protection: Cleaned up %d old global attempts" %
                  (old_count - len(global_attempts)))


def is_ip_locked(ip_address):
    """
    Check if an IP address is currently locked out.

    Args:
        ip_address (str): The IP address to check

    Returns:
        tuple: (is_locked, remaining_time)
            is_locked (bool): True if IP is locked
            remaining_time (int): Seconds remaining in lockout
    """
    with lock:
        if ip_address in failed_attempts:
            data = failed_attempts[ip_address]
            if 'locked_until' in data:
                current_time = time.time()
                if current_time < data['locked_until']:
                    remaining = int(data['locked_until'] - current_time)
                    return True, remaining
                else:
                    # Lockout expired, remove it
                    del data['locked_until']
    return False, 0


def get_required_delay(ip_address):
    """
    Get the required delay before allowing another login attempt.

    Args:
        ip_address (str): The IP address attempting to log in

    Returns:
        int: Delay in seconds (0 if no delay required)
    """
    cleanup_old_entries()

    # Check if IP is locked out
    is_locked, remaining = is_ip_locked(ip_address)
    if is_locked:
        return remaining

    with lock:
        if ip_address not in failed_attempts:
            return 0

        attempt_count = failed_attempts[ip_address].get('attempts', 0)

        if attempt_count == 0:
            return 0

        # Return delay based on attempt count
        if attempt_count in DELAY_SCHEDULE:
            return DELAY_SCHEDULE[attempt_count]
        else:
            return DEFAULT_DELAY


def is_global_attack():
    """
    Check if we're under a global brute force attack (many attempts from various IPs).

    Returns:
        bool: True if global attack detected
    """
    cleanup_old_entries()
    with lock:
        count = len(global_attempts)
        if count >= GLOBAL_MAX_ATTEMPTS:
            msg = "GLOBAL ATTACK DETECTED - %d attempts in last %d seconds" % (count, GLOBAL_WINDOW)
            print("[OpenWebif] Brute force protection: %s" % msg)
            log_to_file("[GLOBAL_ATTACK] %s" % msg)
            return True
    return False


def record_failed_attempt(ip_address, username="unknown"):
    """
    Record a failed login attempt for an IP address.
    Applies progressive delays and lockouts.
    Also tracks globally to detect attacks from changing IPs.

    Args:
        ip_address (str): The IP address that failed to authenticate
        username (str): The username that was attempted
    """
    # Clean up old entries to prevent memory leak
    cleanup_old_entries()

    current_time = time.time()

    with lock:
        # Add to global tracking
        global global_attempts
        global_attempts.append((current_time, ip_address))
        msg = "FAILED LOGIN from IP %s, user '%s' (global count in window: %d)" % (ip_address, username, len(global_attempts))
        print("[OpenWebif] Brute force protection: %s" % msg)
        log_to_file("[FAILED_ATTEMPT] %s" % msg)

        # Per-IP tracking
        if ip_address not in failed_attempts:
            failed_attempts[ip_address] = {
                'attempts': 1,
                'first_attempt': current_time
            }
            msg = "IP %s - First failed attempt recorded" % ip_address
            print("[OpenWebif] Brute force protection: %s" % msg)
            log_to_file("  → %s" % msg)
        else:
            failed_attempts[ip_address]['attempts'] += 1
            attempts = failed_attempts[ip_address]['attempts']
            msg = "IP %s - Failed attempt #%d recorded" % (ip_address, attempts)
            print("[OpenWebif] Brute force protection: %s" % msg)
            log_to_file("  → %s" % msg)

            # Apply lockout after MAX_FAILED_ATTEMPTS
            # So after 5th failed attempt, the 6th+ attempts will be locked out
            if attempts >= MAX_FAILED_ATTEMPTS:
                failed_attempts[ip_address]['locked_until'] = current_time + LOCKOUT_DURATION
                msg = "IP %s - LOCKED OUT for %d seconds (%d minutes)" % (ip_address, LOCKOUT_DURATION, LOCKOUT_DURATION / 60)
                print("[OpenWebif] Brute force protection: %s" % msg)
                log_to_file("[LOCKOUT] %s" % msg)


def record_successful_login(ip_address, username="unknown"):
    """
    Record a successful login and clear failed attempts for an IP address.

    Args:
        ip_address (str): The IP address that successfully authenticated
        username (str): The username that logged in
    """
    with lock:
        if ip_address in failed_attempts:
            attempts = failed_attempts[ip_address].get('attempts', 0)
            del failed_attempts[ip_address]
            msg = "IP %s, user '%s' - Successful login, cleared %d failed attempts" % (ip_address, username, attempts)
            print("[OpenWebif] Brute force protection: %s" % msg)
            log_to_file("[SUCCESS_CLEARED] %s" % msg)
        else:
            msg = "IP %s, user '%s' - Successful login (no prior failures)" % (ip_address, username)
            print("[OpenWebif] Brute force protection: %s" % msg)
            log_to_file("[SUCCESS] %s" % msg)


def check_and_get_delay(ip_address):
	"""
	Check if IP is allowed to proceed and get required delay.
	DOES NOT SLEEP - returns delay value for caller to handle.

	This prevents DoS via time.sleep() blocking the Twisted reactor.

	Args:
		ip_address (str): The IP address attempting to log in

	Returns:
		tuple: (allowed, delay_seconds)
			allowed (bool): True if IP can proceed (possibly after delay), False if locked out
			delay_seconds (int): Seconds to delay before allowing login (0 = immediate)
	"""
	# Check if IP is locked out FIRST - reject immediately
	is_locked, remaining = is_ip_locked(ip_address)
	if is_locked:
		msg = "IP %s is LOCKED OUT for %d more seconds - REJECTING IMMEDIATELY" % (ip_address, remaining)
		print("[OpenWebif] Brute force protection: %s" % msg)
		log_to_file("[BLOCKED_LOCKOUT] %s" % msg)
		return False, 0  # Not allowed, no delay needed (immediate rejection)

	# Check for global attack
	delay = 0
	if is_global_attack():
		global_delay = 10  # 10 second delay for all requests during global attack
		msg = "Global attack mode - %d second delay required for IP %s" % (global_delay, ip_address)
		print("[OpenWebif] Brute force protection: %s" % msg)
		log_to_file("[DELAY_GLOBAL] %s" % msg)
		delay = max(delay, global_delay)

	# Check per-IP delay
	per_ip_delay = get_required_delay(ip_address)
	if per_ip_delay > 0:
		msg = "%d second delay required for IP %s" % (per_ip_delay, ip_address)
		print("[OpenWebif] Brute force protection: %s" % msg)
		log_to_file("[DELAY_PROGRESSIVE] %s" % msg)
		delay = max(delay, per_ip_delay)

	return True, delay  # Allowed (possibly after delay)


def apply_delay(ip_address):
	"""
	DEPRECATED: Use check_and_get_delay() instead to avoid blocking.
	This function is kept for backward compatibility but uses non-blocking approach.

	Apply the required delay for an IP address.
	Uses Twisted reactor for non-blocking delays when available.

	Args:
		ip_address (str): The IP address attempting to log in

	Returns:
		bool: True if allowed (possibly after delay), False if locked out
	"""
	allowed, delay_seconds = check_and_get_delay(ip_address)

	if not allowed:
		return False

	# Try to use Twisted's non-blocking delay if available
	try:
		from twisted.internet import reactor
		if delay_seconds > 0:
			msg = "Applying %d second non-blocking delay for IP %s" % (delay_seconds, ip_address)
			print("[OpenWebif] Brute force protection: %s" % msg)
			# Return a Deferred for async handling
			from twisted.internet import defer
			d = defer.Deferred()
			reactor.callLater(delay_seconds, d.callback, True)
			return d
		else:
			return True
	except ImportError:
		# Twisted not available, fall back to blocking sleep
		if delay_seconds > 0:
			msg = "Applying %d second blocking delay for IP %s (Twisted not available)" % (delay_seconds, ip_address)
			print("[OpenWebif] Brute force protection: %s" % msg)
			time.sleep(delay_seconds)
		return True


def get_status():
    """
    Get current status of brute force protection tracking.
    Useful for monitoring and debugging.

    Returns:
        dict: Status information including tracked IPs and their attempt counts
    """
    cleanup_old_entries()

    with lock:
        status = {
            'tracked_ips': len(failed_attempts),
            'details': []
        }

        current_time = time.time()
        for ip, data in failed_attempts.items():
            ip_status = {
                'ip': ip,
                'attempts': data.get('attempts', 0),
                'first_attempt_age': int(current_time - data.get('first_attempt', current_time))
            }

            is_locked, remaining = is_ip_locked(ip)
            if is_locked:
                ip_status['locked'] = True
                ip_status['lockout_remaining'] = remaining

            status['details'].append(ip_status)

        return status


def reset_ip(ip_address):
    """
    Manually reset/clear tracking for a specific IP address.
    Useful for administrative purposes.

    Args:
        ip_address (str): The IP address to reset

    Returns:
        bool: True if IP was found and reset, False otherwise
    """
    with lock:
        if ip_address in failed_attempts:
            del failed_attempts[ip_address]
            print("[OpenWebif] Brute force protection: Manually reset IP %s" % ip_address)
            return True
    return False


def reset_all():
    """
    Manually reset/clear all tracking data.
    Useful for administrative purposes.
    """
    with lock:
        count = len(failed_attempts)
        failed_attempts.clear()
        print("[OpenWebif] Brute force protection: Manually reset all tracking data (%d IPs cleared)" % count)
