"""Restock drop prediction based on historical OutOfStock → InStock transitions."""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from monitor.state import StateManager


async def get_restock_prediction(state: StateManager, product_id: str) -> dict:
    """Analyze poll history and return restock prediction statistics.

    Returns:
        dict with keys: restock_count, avg_interval_days, last_restock,
        next_restock_estimate, confidence, std_dev_days
    """
    history = await state.get_poll_history(product_id, limit=5000)

    if not history:
        return _empty_prediction()

    # History comes newest-first; reverse for chronological order
    history = list(reversed(history))

    # Find OutOfStock → InStock transitions
    restocks: list[datetime] = []
    prev_availability = None

    for poll in history:
        avail = poll.get("availability")
        if prev_availability == "OutOfStock" and avail == "InStock":
            ts = poll.get("timestamp")
            if ts:
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                restocks.append(ts)
        prev_availability = avail

    restock_count = len(restocks)

    if restock_count == 0:
        return _empty_prediction()

    last_restock = restocks[-1]

    if restock_count < 2:
        return {
            "restock_count": 1,
            "avg_interval_days": None,
            "last_restock": last_restock.isoformat(),
            "next_restock_estimate": None,
            "confidence": "low",
            "std_dev_days": None,
        }

    # Calculate intervals between consecutive restocks
    intervals: list[float] = []
    for i in range(1, len(restocks)):
        delta = (restocks[i] - restocks[i - 1]).total_seconds() / 86400
        intervals.append(delta)

    avg_interval = sum(intervals) / len(intervals)
    std_dev = math.sqrt(sum((x - avg_interval) ** 2 for x in intervals) / len(intervals))

    next_estimate = last_restock + timedelta(days=avg_interval)

    if restock_count >= 5:
        confidence = "high"
    elif restock_count >= 3:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        "restock_count": restock_count,
        "avg_interval_days": round(avg_interval, 1),
        "last_restock": last_restock.isoformat(),
        "next_restock_estimate": next_estimate.isoformat(),
        "confidence": confidence,
        "std_dev_days": round(std_dev, 1),
    }


def _empty_prediction() -> dict:
    return {
        "restock_count": 0,
        "avg_interval_days": None,
        "last_restock": None,
        "next_restock_estimate": None,
        "confidence": "low",
        "std_dev_days": None,
    }
