"""Interpret quality labels shared by stream selection and downgrade."""
import re


def stream_quality(label):
    if not isinstance(label, str):
        return None
    match = re.search(r'\d+[kK]?', label)
    if not match:
        return None
    value = match.group(0).lower()
    if value in ('4k', '8k'):
        return {'4k': 2160, '8k': 4320}[value]
    try:
        return int(value.rstrip('k'))
    except ValueError:
        return None
