from dataclasses import dataclass, field
from typing import Dict, Optional


@dataclass
class CoreData:
    """Data structure for HTTP request metrics.

    Captures essential request information for analytics and monitoring.
    """
    token: str
    source_ip: str
    endpoint: str
    scheme: bool
    method: str
    timestamp: str  # ISO 8601 format timestamp
    custom_data: Optional[Dict] = None

    # Additional request details
    headers: Optional[Dict] = None
    query_params: Optional[Dict] = None
    body: Optional[Dict] = None
    user_agent: Optional[str] = None
    user_id: Optional[str] = None
