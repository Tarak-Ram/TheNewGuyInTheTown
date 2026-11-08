import os
from contextlib import asynccontextmanager

from nguit_tools.health import create_app

from relocation_api import account, advisor, agreements, auth, calls, plans
from relocation_api.migrate import migrate
from relocation_api.ratelimit import RateLimitMiddleware


@asynccontextmanager
async def lifespan(_app):
    # Local stack only: compose sets RUN_MIGRATIONS=true. Staging/prod run it as a job.
    if os.environ.get("RUN_MIGRATIONS", "").lower() == "true":
        migrate(os.environ["DATABASE_URL"])
    yield


app = create_app("api", "Relocation API", lifespan=lifespan)
app.add_middleware(RateLimitMiddleware)
app.include_router(auth.router)
app.include_router(plans.router)
app.include_router(advisor.router)
app.include_router(calls.router)
app.include_router(agreements.router)
app.include_router(account.router)
