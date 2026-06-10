"""
handlers/utils.py -- Shared utilities for all Tier-0 domain handlers.
"""

LIST_CAP = 50   # default max rows for any list response


def large_data_note(shown, total, entity="records"):
    """Returns a blockquote footer when a list has been capped."""
    remaining = total - shown
    prompt = "show all " + entity
    return (
        "> **Large dataset** — showing top "
        + str(shown) + " of " + str(total) + " " + entity + ". "
        + str(remaining) + " more not shown. "
        + "Would you like to see **all " + str(total) + "**? "
        + 'Just say **"' + prompt + '"** and I will share the complete list.'
    )
