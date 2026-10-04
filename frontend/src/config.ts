// Ask is disabled while it's being improved (backend mirror: CHAT_ENABLED=false on Railway).
// Flipping this back to true restores the search-bar Ask mode, the homepage "Try Now"
// bubble, and Ask session restore — no other code changes needed.
export const ASK_ENABLED = false;

// Hours per week and comment counts come from the student questionnaire, which does not
// exist yet. While false, the professor page hides Hrs/Week and Total Comments and the
// course page hides Avg Hrs/Week. Flip to true once the questionnaire source is live.
export const SHOW_SURVEY_STATS = false;
