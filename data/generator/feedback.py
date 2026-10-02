"""Synthetic customer-feedback text. All text is generated from templates (SYNTHETIC)."""

THEMES = {
    "ai_coach_positive": [
        "My AI coach plan keeps me on track.", "The AI coach adjusts my workouts really well.",
        "Love the daily tips from the AI coach.", "AI coach made my routine easier to stick with.",
        "The coach feels personal and the suggestions are spot on.",
    ],
    "ai_coach_negative": [
        "The AI coach keeps repeating the same advice.", "AI coach suggestions feel generic after a few weeks.",
        "The coach ignored my injury notes, not impressed.",
    ],
    "ai_coach_neutral": [
        "Tried the AI coach, it is okay.", "AI coach is fine but I mostly follow my own plan.",
    ],
    "onboarding_complaint": [
        "Got stuck on step 2 of setup and could not continue.",
        "Onboarding froze and I could not finish setting up my profile.",
        "The setup process is confusing, gave up halfway.",
        "Cannot complete onboarding on my phone, it keeps looping.",
        "Signed up but never got through the welcome flow.",
        "Setup wizard crashed at the goals screen.",
    ],
    "pricing_sensitive": [
        "Premium is too expensive for what it offers.", "I will cancel if the price goes up.",
        "The price jump from 9.99 is hard to justify.", "Too pricey compared with other fitness apps.",
        "Considering downgrading because of the subscription cost.",
    ],
    "pricing_value": [
        "Premium is worth the money for me.", "Happy to pay for the workout plans.",
        "Good value for the price.",
    ],
    "community_positive": [
        "Challenges keep me motivated.", "Love competing with friends in the weekly challenge.",
        "The community challenges got me back into a routine.",
    ],
    "community_negative_notifications": [
        "Too many challenge notifications, they stress me out.",
        "The challenge reminders are pushy and I muted the app.",
        "I joined a challenge and now get pinged constantly.",
    ],
    "community_neutral": [
        "Joined a challenge, not really for me.", "Challenges are fine but I train alone.",
    ],
    "generic_positive": [
        "Great workout library.", "Clean design and easy to use.", "Does what I need for tracking runs.",
    ],
    "generic_negative": [
        "Battery drain is noticeable during workouts.", "Sync with my watch is flaky sometimes.",
    ],
    "generic_neutral": [
        "Decent app overall.", "Works as expected.",
    ],
}

THEME_SENTIMENT = {
    "ai_coach_positive": "positive", "ai_coach_negative": "negative", "ai_coach_neutral": "neutral",
    "onboarding_complaint": "negative", "pricing_sensitive": "negative", "pricing_value": "positive",
    "community_positive": "positive", "community_negative_notifications": "negative",
    "community_neutral": "neutral", "generic_positive": "positive", "generic_negative": "negative",
    "generic_neutral": "neutral",
}

SUFFIXES = ["", "", "", " Overall decent app.", " Using it most days.", " Been a user for a while.", " Thanks."]


def render(theme: str, rng) -> str:
    phrases = THEMES[theme]
    return phrases[int(rng.integers(0, len(phrases)))] + SUFFIXES[int(rng.integers(0, len(SUFFIXES)))]


def rating_for(sentiment: str, source: str, rng):
    if source == "support_ticket":
        return None
    if sentiment == "positive":
        return int(rng.integers(4, 6))
    if sentiment == "neutral":
        return 3
    return int(rng.integers(1, 3))
