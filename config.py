"""Monitor configuration: what to watch and how often."""

API_BASE = "https://seat-customer-api-prod.mostanet.ru"
SITE_URL = "https://mostanet.ru/"

CHECK_INTERVAL_SECONDS = 180        # poll every 3 minutes
REMIND_INTERVAL_SECONDS = 30 * 60   # re-alert every 30 min while tickets remain
API_DOWN_ALERT_SECONDS = 30 * 60    # tell admin if API unreachable this long

# Stop IDs come from GET /customer/busstops?name=...
KURILSK_PORT = "3da1de08-c824-4839-9117-6de36bdc5f49"
YUZHNO_KURILSK_PORT = "a4ad8d14-d876-405f-bb7b-f0bfe966a499"
MALOKURILSKOE_PORT = "778fc8a1-51ac-4f91-b45c-8e79fcc2d295"

WATCHES = [
    {
        "key": "kurilsk-yuk-2026-08-15",
        "date": "2026-08-15",
        "from_id": KURILSK_PORT,
        "from_name": "Курильск порт",
        "to_id": YUZHNO_KURILSK_PORT,
        "to_name": "Южно-Курильск порт",
    },
]
