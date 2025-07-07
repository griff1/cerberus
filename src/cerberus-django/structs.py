from dataclasses import dataclass

@dataclass
class CoreData:
    token: str
    source_ip: str
    endpoint: str
    scheme: bool
    method: str
    custom_data: dict = None  # Dictionary to store custom metrics from endpoints
