"""Decision Debt Radar API.

Day 3: deterministic DDI / NBE engines, lifecycle, assessment versioning, human review and decision record,
behind a demo role switcher (X-Demo-User header, not authentication). No LLM, agents or analytics yet.
"""

from fastapi import FastAPI

from app.api.routes import assessments, decisions, system
from app.core.errors import install_error_handlers


def create_app() -> FastAPI:
    app = FastAPI(
        title="Decision Debt Radar API",
        version="0.3.0",
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
    return app


app = create_app()
