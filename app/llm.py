"""Draft the message L1 sends to the client. Works without an API key (template);
uses Claude when ANTHROPIC_API_KEY is set and the `llm` extra is installed."""
import os

MODEL = os.environ.get("RIDEOPS_LLM_MODEL", "claude-opus-5-5")


def template_message(client_name: str, description: str, missing: list[str]) -> str:
    items = "\n".join(f"- {m}" for m in missing)
    return (
        f"Hi {client_name} team,\n\n"
        f"Thanks for reporting \"{description}\". To get this fixed in one go, could you share:\n"
        f"{items}\n\n"
        "As soon as we have these we'll take it forward and keep you posted.\n\n"
        "Regards,\nRideOps Support"
    )


def llm_available() -> bool:
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return False
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return True


def draft_message(client_name: str, description: str, missing: list[str]) -> tuple[str, str]:
    """Returns (message, source) where source is "Claude" or "template"."""
    fallback = template_message(client_name, description, missing)
    if not missing or not llm_available():
        return fallback, "template"
    import anthropic

    try:
        response = anthropic.Anthropic().messages.create(
            model=MODEL,
            max_tokens=1000,
            output_config={"effort": "low"},
            system=(
                "You write short, polite emails from RideOps L1 support to a corporate client's transport admin. "
                "Ask only for the listed details, explain in one sentence why they help, no more than 120 words, "
                "plain text, sign off as RideOps Support."
            ),
            messages=[{"role": "user", "content": (
                f"Client: {client_name}\nIssue: {description}\nDetails we still need:\n" + "\n".join(missing)
            )}],
        )
    except anthropic.APIError:
        return fallback, "template"
    if response.stop_reason == "refusal":
        return fallback, "template"
    text = "".join(b.text for b in response.content if b.type == "text").strip()
    return (text, "Claude") if text else (fallback, "template")
