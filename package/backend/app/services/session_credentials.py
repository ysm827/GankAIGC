from app.models.models import OptimizationSession


def clear_transient_session_api_keys(session: OptimizationSession) -> bool:
    """Erase request-scoped BYOK secrets once a task reaches a terminal state."""
    if session.credential_source != "request":
        return False

    changed = any(
        value
        for value in (
            session.polish_api_key,
            session.enhance_api_key,
            session.emotion_api_key,
        )
    )
    session.polish_api_key = None
    session.enhance_api_key = None
    session.emotion_api_key = None
    return changed
