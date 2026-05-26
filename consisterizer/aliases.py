"""Consisterizer aliases for quick preset configurations.

Each alias is a dict consumed by consisterizer() to prefill fields,
toggle options, and select scripts.
"""

import logging

logger = logging.getLogger(__name__)

# Bulk check-in preset for clearing assignments and expected check-in.
bulkCheckIn = {
          "title": "Bulk Check-in",
          "batch_mode": True,
          "maintain_defaults": True,
          # Clear assignment fields for bulk return processing.
          "set": {
            "expected_checkin": "{empty}",
            "assigned_to": "{empty}"
          },
          # Reset name to default for the active profile.
          "reset": ["name",],
          "scripts": []
        }

# Count the number of aliases defined in this module.
_ALIAS_COUNT = sum(1 for _v in list(locals().values()) if isinstance(_v, dict))
logger.info("aliases module loaded: %s aliases", _ALIAS_COUNT)
