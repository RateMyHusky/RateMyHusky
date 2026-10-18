// Readable names for the teaching-style tags from /api/professors/<slug>/tags
export const TAG_LABELS: Record<string, string> = {
  requires_textbook: 'Textbook required',
  mandatory_attendance: 'Attendance mandatory',
  heavy_workload: 'Heavy workload',
  group_projects: 'Group projects',
  curved_grading: 'Curves grades',
  pop_quizzes: 'Pop quizzes',
  recorded_lectures: 'Recorded lectures',
  office_hours_helpful: 'Helpful office hours',
  hard_exams: 'Tough exams',
  easy_a: 'Easy A',
  engaging_lecturer: 'Engaging lectures',
  extra_credit: 'Extra credit',
  participation_grade: 'Participation matters',
  accommodating: 'Flexible deadlines',
};

export const tagLabel = (tag: string) => TAG_LABELS[tag] ?? tag.replace(/_/g, ' ');
