"""Terminal resource history and the shared publication retention policy."""
import datetime as dt
import math
import time


TERMINAL_RETENTION = 7 * 24 * 60 * 60


def terminal_time(value, current):
    """Accept epoch seconds or timezone-aware ISO times, never future evidence."""
    try:
        if isinstance(value, str):
            stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            if stamp.tzinfo is None:
                return None
            value = stamp.timestamp()
        if type(value) in (int, float) and math.isfinite(value) and 0 < value <= current:
            return value
    except (ValueError, OverflowError, OSError):
        pass
    return None


def record_terminal(resource, *evidence):
    if resource.get('status') not in ['closed', 'failed']:
        return
    current = time.time()
    if terminal_time(resource.get('terminal_at'), current) is not None:
        return
    # Submission, telemetry and directory times cannot date a closure. Old
    # metadata without terminal evidence gets a full retention period from now.
    stamp = next((stamp for value in evidence
                  if (stamp := terminal_time(value, current)) is not None), current)
    resource['terminal_at'] = stamp


def published_resources(resources):
    """Filter only the published view; retain all internal records and files."""
    current = time.time()
    result = {}
    for key, resource in resources.items():
        stamp = terminal_time(resource.get('terminal_at'), current)
        if (resource.get('status') in ['closed', 'failed'] and stamp is not None
                and current - stamp >= TERMINAL_RETENTION):
            continue
        result[key] = resource
    return result
