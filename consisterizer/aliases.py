"""Consisterizer aliases for quick preset configurations.

Each alias is a dict consumed by consisterizer() to prefill fields,
toggle options, and select scripts.
"""

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
