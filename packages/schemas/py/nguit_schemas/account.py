from pydantic import BaseModel


class DeletionOut(BaseModel):
    status: str  # "deleted"
    plans: int
    calls: int
    agreements: int
    files_pending: int  # stored files that could not be deleted yet; the daily job retries them
