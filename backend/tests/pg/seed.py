"""Minimal read-model rows, in pipeline.read_models' column shapes."""

CATALOG = [{
    "slug": "alice-smith", "name": "Alice Smith", "name_key": "alice smith",
    "department": "Computer Science", "college": "Khoury", "avg_rating": 4.5,
    "rmp_rating": 4.4, "num_ratings": 10, "total_reviews": 12,
    "would_take_again_pct": 90.0, "difficulty": 3.1,
    "professor_url": "https://www.ratemyprofessors.com/professor/1",
    "image_url": None, "focus_x": None, "focus_y": None, "total_comments": 5,
}]

COURSES = [{
    "code": "CS2500", "name": "Fundamentals of Computer Science 1",
    "department": "Computer Science", "subject": "CS",
    "search_text": "cs2500 fundamentals of computer science 1",
    "avg_rating": 4.1, "difficulty": 2.5, "num_ratings": 7,
}]

SUMMARIES = [
    {"professor_slug": "alice-smith", "course_code": "", "source": "blend",
     "rating": 4.5, "difficulty": 3.1, "would_take_again_pct": 90.0,
     "num_ratings": 12, "num_comments": 5, "hours_per_week": None,
     "rating_distribution": {"5": 3}, "grade_distribution": {}},
    {"professor_slug": "", "course_code": "CS2500", "source": "blend",
     "rating": 4.1, "difficulty": 2.5, "would_take_again_pct": None,
     "num_ratings": 7, "num_comments": 2, "hours_per_week": None,
     "rating_distribution": None, "grade_distribution": None},
]

COUNTS = {"professors": 1, "courses": 1, "comments": 5, "departments": 1}
