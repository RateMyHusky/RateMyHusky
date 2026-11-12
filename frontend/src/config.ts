// Ask logs each question with the account id, and no IP (ask_log, deleted after 30 days:
// ASK_LOG_RETENTION_DAYS in server.py) and sends questions to Groq. The Privacy Policy and
// Terms don't mention Ask yet, and Groq is only listed there for rating comments.
// This flag gates the floating Ask widget, the homepage "Try Now" bubble and the
// ban-appeal feedback option. The backend serves Ask regardless of it.
export const ASK_ENABLED = true;

// Reviews & Mentions on the professor page counts questionnaire comments plus Reddit mentions.
// Hidden while false. Avg Hrs / Week is always shown on both pages and reads "—" until ratings
// report hours.
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
