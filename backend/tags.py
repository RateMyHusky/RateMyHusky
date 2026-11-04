# Tags we pull out of reviews. The model can only pick from TAG_TAXONOMY,
# anything else gets dropped.
#
# To add a tag: add it to TAG_TAXONOMY and TAG_HINTS, then bump TAXONOMY_VERSION
# so the next run goes back over reviews that were already done.

TAXONOMY_VERSION = 1

TAG_TAXONOMY = {
    "heavy_workload": "Frequent or time-consuming assignments/homework",
    "group_projects": "Significant group project component",
    "curved_grading": "Grades are curved",
    "pop_quizzes": "Unannounced quizzes",
    "recorded_lectures": "Lectures are recorded or available online",
    "office_hours_helpful": "Office hours described as useful or accessible",
    "hard_exams": "Exams described as difficult",
    "easy_a": "Class or grading described as easy",
    "engaging_lecturer": "Lecturing style praised as engaging",
    "extra_credit": "Extra credit opportunities offered",
    "participation_grade": "Participation counts toward the grade",
    "accommodating": "Flexible with deadlines or accommodations",
}

# Keywords a review needs before a tag can apply. Each tag has one or more groups
# and the review has to hit every group, so hard_exams needs an exam word AND a
# difficulty word instead of just "final" (which is in almost every review).
# Used for the pre-filter and to throw out tags the model made up.
TAG_HINTS = {
    "heavy_workload": [["workload", "lots of homework", "lot of homework", "a lot of work", "lots of work",
                        "heavy", "time consuming", "time-consuming", "busy work", "busywork"]],
    "group_projects": [["group project", "group projects", "group work", "team project", "team projects",
                        "partner project", "partner projects"]],
    "curved_grading": [["curve", "curved", "curves", "curving"]],
    "pop_quizzes": [["pop quiz", "pop quizzes", "surprise quiz", "surprise quizzes", "unannounced"]],
    "recorded_lectures": [["recorded", "recordings", "lecture videos", "records lectures", "records the lectures"]],
    "office_hours_helpful": [["office hours", "office hour"]],
    "hard_exams": [["exam", "exams", "test", "tests", "midterm", "midterms", "final", "finals"],
                   ["hard", "harder", "difficult", "tough", "brutal", "impossible", "challenging"]],
    "easy_a": [["easy a", "easy class", "easy course", "easy grader", "easy to get an a",
                "easy to get a good grade", "gpa booster", "free a"]],
    "engaging_lecturer": [["engaging", "amazing lectures", "great lectures", "interesting lectures",
                           "great lecturer", "passionate", "entertaining", "hilarious"]],
    "extra_credit": [["extra credit", "bonus points", "bonus"]],
    "participation_grade": [["participation", "participate"]],
    "accommodating": [["extension", "extensions", "flexible", "accommodating", "accommodations",
                       "lenient", "understanding about"]],
}

# RMP's own tags that match ours
RMP_TAG_MAP = {
    "participation matters": "participation_grade",
    "extra credit": "extra_credit",
    "group projects": "group_projects",
    "amazing lectures": "engaging_lecturer",
    "lots of homework": "heavy_workload",
    "beware of pop quizzes": "pop_quizzes",
    "accessible outside class": "office_hours_helpful",
}
