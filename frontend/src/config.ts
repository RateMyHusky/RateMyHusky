// Ask is disabled while it's being improved (backend mirror: CHAT_ENABLED=false on Railway).
// Before flipping it back on, update the Privacy Policy and Terms: neither mentions Ask. It
// logs each question with the account id and hashed IP (ask_log, deleted after 30 days:
// ASK_LOG_RETENTION_DAYS in server.py) and sends questions to Groq, which isn't in either
// document's third-party list. While Ask is off, nothing is logged.
// This flag gates the floating Ask widget, the homepage "Try Now" bubble and the
// ban-appeal feedback option.
export const ASK_ENABLED = false;

// Hours per week and comment counts come from the student questionnaire, which does not
// exist yet. While false, the professor page hides Hrs/Week and Reviews & Mentions and the
// course page hides Avg Hrs/Week. Flip to true once the questionnaire source is live.
export const SHOW_SURVEY_STATS = false;

// The first term the course-schedule history covers: scraper/banner_scrape.py's
// DEFAULT_SINCE_TERM (202210). The FAQ and Privacy Policy state it; change it here
// when the backfill floor moves.
export const BANNER_SINCE = 'Fall 2021';

// The /rate form, the professor page's rate button, prompts and reviews tab, and the rating text
// in the FAQ, Privacy Policy and Terms. Live everywhere since the v2.2.0 launch.
export const RATE_ENABLED = true;

// The day the weekly data refresh runs (.github/workflows/data-refresh.yml cron, 10:00 UTC
// Sunday). The /rate thank-you step names it; change both together.
export const REFRESH_DAY = 'Sunday';
