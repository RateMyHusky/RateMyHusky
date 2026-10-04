# Tags we pull out of reviews. The model can only pick from TAG_TAXONOMY,
# anything else gets dropped. To add a tag, add it here + a few keywords in TAG_HINTS.

TAG_TAXONOMY = {
    "requires_textbook": "Professor requires or strongly recommends buying a textbook",
    "mandatory_attendance": "Attendance is tracked and affects the grade",
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

# if a comment has none of these words we don't bother sending it to the model
TAG_HINTS = {
    "requires_textbook": ["textbook", "book", "reading", "readings"],
    "mandatory_attendance": ["attendance", "attend", "show up", "roll call", "clicker", "iclicker"],
    "heavy_workload": ["workload", "homework", "hw", "assignment", "assignments", "busy work", "time consuming", "lot of work"],
    "group_projects": ["group", "groups", "team project", "partner"],
    "curved_grading": ["curve", "curved", "curves"],
    "pop_quizzes": ["quiz", "quizzes"],
    "recorded_lectures": ["recorded", "recording", "recordings", "online", "video", "videos"],
    "office_hours_helpful": ["office hours", "office hour"],
    "hard_exams": ["exam", "exams", "test", "tests", "midterm", "midterms", "final"],
    "easy_a": ["easy", "gpa booster", "free a"],
    "engaging_lecturer": ["engaging", "lecture", "lectures", "funny", "interesting", "passionate"],
    "extra_credit": ["extra credit", "bonus"],
    "participation_grade": ["participation", "participate"],
    "accommodating": ["extension", "extensions", "flexible", "deadline", "deadlines", "accommodating", "accommodations", "lenient", "understanding"],
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
