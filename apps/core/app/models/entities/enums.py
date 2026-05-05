from enum import Enum


class JobStatus(str, Enum):
    CREATED = "created"
    UPLOADED = "uploaded"
    PROCESSING = "processing"
    WAITING_PROVIDER = "waiting_provider"
    FINALIZING = "finalizing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELED = "canceled"


class ProviderRequestStatus(str, Enum):
    PENDING = "pending"
    SUBMITTED = "submitted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
