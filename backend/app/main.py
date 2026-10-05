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
from app.core.errors import install_error_handlers


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
    app.include_router(system.router)
    app.include_router(decisions.router)
    app.include_router(assessments.router)
    app.include_router(analytics.router)
    app.include_router(customer.router)
    return app


app = create_app()
