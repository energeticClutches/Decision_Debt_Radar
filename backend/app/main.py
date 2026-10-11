"""Decision Debt Radar API.

Day 3: deterministic DDI / NBE engines, lifecycle, assessment versioning, human review and decision record,
behind a demo role switcher (X-Demo-User header, not authentication).
Day 4: deterministic data and analytics foundation (data quality, experiment statistics, heterogeneity, generated
evidence with traceability, SQL guard, pipeline).
Day 5: the first LLM boundary: customer evidence (LLM classification, human approval), evidence synthesis, a code-governed
Reviewer, and briefs. DDI v0.1 and NBE v0.2 are unchanged: the model never scores, never chooses a stance and never recommends.
"""

from fastapi import FastAPI

from app.api.routes import analytics, assessments, customer, decisions, system
from app.core.config import get_settings
from app.core.errors import install_error_handlers
from app.core.middleware import RequestMiddleware, configure_request_logging
from app.core.ratelimit import SlidingWindowLimiter


def create_app() -> FastAPI:
    app = FastAPI(
        title="Decision Debt Radar API",
        version="0.5.0",
        description=(
            "Agentic decision-intelligence portfolio project. "
            "DDI is a proposed evidence-risk heuristic, not an industry standard and not a measure of decision quality. "
            "All FitConnect data is synthetic. Identity is a demo role switcher (X-Demo-User), not authentication."
        ),
    )
    install_error_handlers(app)
    settings = get_settings()
    # Deploy (DDR_ENV=production): a request log line on stdout and the in-process rate limit. Neither changes a response otherwise.
    limiter = (SlidingWindowLimiter(settings.ddr_rate_limit_window_seconds, settings.ddr_rate_limit_mutations, settings.ddr_rate_limit_pipeline)
               if settings.rate_limit_enabled else None)
    if settings.log_requests:
        configure_request_logging()
    if limiter is not None or settings.log_requests:
        app.add_middleware(RequestMiddleware, settings=settings, limiter=limiter, log_requests=settings.log_requests)
    app.include_router(system.router)
    app.include_router(decisions.router)
    app.include_router(assessments.router)
    app.include_router(analytics.router)
    app.include_router(customer.router)
    return app


app = create_app()
