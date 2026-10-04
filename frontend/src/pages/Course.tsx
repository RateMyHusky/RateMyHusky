import { useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import StarRating from '../components/StarRating';
import NotFound from './NotFound';
import LoadError from '../components/LoadError';
import { fetchCourseData } from '../api/api';
import type { CourseDetail } from '../api/api';
import Footer from '../components/Footer';
import { getInitials, stripPrefix } from '../utils/nameUtils';
import Breadcrumbs from '../components/Breadcrumbs';
import Seo from '../components/Seo';
import BookmarkButton from '../components/BookmarkButton';
import { SHOW_SURVEY_STATS } from '../config';
import './Course.css';

const INITIAL_PROFESSORS_VISIBLE = 5;
const PROFESSORS_VISIBLE_STEP = 5;
const TOP_PROFESSORS = 10;

/* Display names for summary.bySource keys; an unlisted source shows its key. */
const SOURCE_LABELS: Record<string, string> = { rmp: 'RMP' };

const Course = () => {
	const { code = '' } = useParams<{ code: string }>();
	const [course, setCourse] = useState<CourseDetail | null>(null);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState<'not_found' | 'failed' | null>(null);
	const [visibleCount, setVisibleCount] = useState(INITIAL_PROFESSORS_VISIBLE);
	const [showBackToTop, setShowBackToTop] = useState(false);
	const tableWrapRef = useRef<HTMLDivElement>(null);
	const [tableAtStart, setTableAtStart] = useState(true);
	const [tableAtEnd, setTableAtEnd] = useState(false);

	useEffect(() => {
		let cancelled = false;
		setLoading(true);
		setLoadError(null);
		fetchCourseData(code).then((res) => {
			if (cancelled) return;
			if (res.ok) setCourse(res.data);
			else setLoadError(res.status === 404 ? 'not_found' : 'failed');
			setLoading(false);
		});
		return () => { cancelled = true; };
	}, [code]);

	useEffect(() => {
		const handler = () => setShowBackToTop(window.scrollY > 300);
		window.addEventListener('scroll', handler, { passive: true });
		handler();
		return () => window.removeEventListener('scroll', handler);
	}, []);

	useEffect(() => {
		const el = tableWrapRef.current;
		if (!el) return;
		const check = () => {
			setTableAtStart(el.scrollLeft <= 10);
			setTableAtEnd(el.scrollLeft + el.clientWidth >= el.scrollWidth - 10);
		};
		check();
		el.addEventListener('scroll', check, { passive: true });
		window.addEventListener('resize', check);
		return () => {
			el.removeEventListener('scroll', check);
			window.removeEventListener('resize', check);
		};
	}, [course]);

	if (loading) {
		return (
			<div className="course-page">
				<div className="course-shell">
					<div className="course-loading">Loading course data...</div>
				</div>
			</div>
		);
	}

	if (loadError === 'not_found') return <NotFound />;
	if (loadError || !course) return <div className="course-page"><LoadError /></div>;

	const summary = course.summary;
	const professors = course.professors;
	const visibleProfessors = professors.slice(0, visibleCount);
	const hasMore = visibleCount < professors.length;
	const canCollapse = visibleCount > INITIAL_PROFESSORS_VISIBLE;
	const hasExpandable = professors.length > INITIAL_PROFESSORS_VISIBLE;
	/* professors[] arrives sorted by rating count, most first. */
	const topProfessors = professors.slice(0, TOP_PROFESSORS);
	const breakdown = Object.entries(summary.bySource).filter(([, v]) => v.rating !== null);

	/* Mirrors render.course_html's description exactly (crawler copy and page must agree). */
	const courseSeoDescription =
		`${course.code} (${course.name}) course reviews and ratings at Northeastern (NEU). ` +
		(summary.rating != null ? `Average rating ${summary.rating.toFixed(1)}/5. ` : '') +
		`Compare professors with RateMyProfessor reviews.`;

	const courseCanonical = `https://ratemyhusky.com/courses/${code}`;
	const courseJsonLd: Record<string, unknown> = {
		'@context': 'https://schema.org',
		'@type': 'Course',
		name: `${course.code} — ${course.name}`,
		courseCode: course.code,
		provider: { '@type': 'CollegeOrUniversity', name: 'Northeastern University' },
		...(course.catalog?.description ? { description: course.catalog.description } : {}),
	};
	if (summary.rating != null && summary.numRatings) {
		courseJsonLd.aggregateRating = {
			'@type': 'AggregateRating',
			ratingValue: summary.rating,
			ratingCount: summary.numRatings,
			bestRating: 5,
		};
	}
	const courseBreadcrumbJsonLd = {
		'@context': 'https://schema.org',
		'@type': 'BreadcrumbList',
		itemListElement: [
			{ '@type': 'ListItem', position: 1, name: 'Home', item: 'https://ratemyhusky.com/' },
			{ '@type': 'ListItem', position: 2, name: 'Courses', item: 'https://ratemyhusky.com/courses' },
			{ '@type': 'ListItem', position: 3, name: course.code, item: courseCanonical },
		],
	};

	return (
		<div className="course-page">
			<Seo
				title={`${course.code} Reviews — ${course.name} at Northeastern`}
				description={courseSeoDescription}
				canonical={courseCanonical}
				jsonLd={[courseJsonLd, courseBreadcrumbJsonLd]}
			/>
			<div className="course-shell">
				<Breadcrumbs items={[
					{ label: 'Courses', to: '/courses' },
					{ label: course.code },
				]} />

				<header className="course-hero">
					<div>
						<p className="course-code">{course.code}</p>
						<h1>
							{course.name}
							<BookmarkButton itemType="course" itemKey={course.code} size="md" className="course-hero-bookmark" />
						</h1>
						<p className="course-dept">{course.department}</p>
					</div>
				</header>

				{course.catalog && (course.catalog.description || course.catalog.credits || course.catalog.prerequisites
					|| course.catalog.corequisites || course.catalog.nupath.length > 0) && (
					<section className="course-panel course-catalog-info">
						<div className="course-panel-header">
							<h2>About This Course</h2>
						</div>
						{course.catalog.description && <p className="course-catalog-desc">{course.catalog.description}</p>}
						<dl className="course-catalog-facts">
							{course.catalog.credits && <div><dt>Credits</dt><dd>{course.catalog.credits}</dd></div>}
							{course.catalog.prerequisites && <div><dt>Prerequisites</dt><dd>{course.catalog.prerequisites}</dd></div>}
							{course.catalog.corequisites && <div><dt>Corequisites</dt><dd>{course.catalog.corequisites}</dd></div>}
							{course.catalog.nupath.length > 0 && (
								<div>
									<dt>NUpath</dt>
									<dd className="course-catalog-nupath">
										{course.catalog.nupath.map(n => <span key={n} className="course-catalog-tag">{n}</span>)}
									</dd>
								</div>
							)}
						</dl>
					</section>
				)}

				<section className="course-stats-grid">
					<article className="course-stat-card">
						<strong className="course-stat-value">{summary.rating != null ? summary.rating.toFixed(2) : '—'}</strong>
						<StarRating rating={summary.rating ?? 0} size="lg" />
						<span className="course-stat-label" style={{ display: 'block', textAlign: 'center', position: 'relative' }}>
							Overall Rating
							{breakdown.length > 0 && (
								<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ position: 'absolute', top: '50%', transform: 'translateY(-50%)', marginLeft: '4px', opacity: 0.6 }}><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
							)}
						</span>
						{breakdown.length > 0 && (
							<div className="course-stat-breakdown">
								{breakdown.map(([source, v]) => (
									<span key={source}>{SOURCE_LABELS[source] ?? source.toUpperCase()}: {v.rating!.toFixed(2)}</span>
								))}
							</div>
						)}
					</article>
					<DifficultyStatCard value={summary.difficulty} />
					<StatCard label="Ratings" value={summary.numRatings ? summary.numRatings.toLocaleString() : '—'} />
					<StatCard label="Professors" value={professors.length.toLocaleString()} />
					{SHOW_SURVEY_STATS && (
						<StatCard label="Avg Hrs / Week" value={summary.hoursPerWeek != null ? `${summary.hoursPerWeek.toFixed(1)}h` : '—'} />
					)}
				</section>

				{topProfessors.length > 0 && (
					<section className="course-panel">
						<div className="course-panel-header">
							<h2>Most-Rated Professors</h2>
						</div>
						<div className="course-top-prof-grid">
							{topProfessors.map((prof, index) => (
								<Link
									to={`/professors/${prof.slug}`}
									state={{ fromPage: { label: `${course.code} – ${course.name}`, url: `/courses/${code}` } }}
									className="course-top-prof-card"
									key={prof.slug}
									aria-label={`View ${prof.name}`}
								>
									<div className="course-top-prof-photo">
										{prof.imageUrl ? (
											<img
												className="course-top-prof-img"
												src={prof.imageUrl}
												alt={prof.name}
												style={{ objectPosition: `${prof.focusX}% ${prof.focusY}%` }}
											/>
										) : (
											<div className="course-top-prof-avatar" aria-hidden="true">
												{getInitials(prof.name)}
											</div>
										)}
										<span className="course-top-prof-rank">#{index + 1}</span>
									</div>
									<div className="course-top-prof-body">
										<div className="course-top-prof-body-top">
											<div className="course-top-prof-rating">
												{prof.rating != null ? (
													<>
														<span className="course-top-prof-avg">{prof.rating.toFixed(1)}</span>
														<StarRating rating={prof.rating} size="sm" />
													</>
												) : (
													<span className="course-top-prof-avg">—</span>
												)}
											</div>
											<h3 className="course-top-prof-name">
												{stripPrefix(prof.name)}
											</h3>
										</div>
										<div className="course-top-prof-footer">
											<span>{prof.numRatings.toLocaleString()} rating{prof.numRatings === 1 ? '' : 's'}</span>
											<span className="course-top-prof-footer--right">{prof.difficulty != null ? `${prof.difficulty.toFixed(1)} difficulty` : '—'}</span>
										</div>
									</div>
								</Link>
							))}
						</div>
					</section>
				)}

				<section className="course-panel">
					<div className="course-panel-header">
						<h2>Professors</h2>
					</div>
					{professors.length === 0 ? (
						<p className="course-empty">No professor ratings for this course yet.</p>
					) : (
						<div className={`instructor-scroll-wrap${!tableAtStart ? ' fade-left' : ''}${!tableAtEnd ? ' fade-right' : ''}`}>
							<div className="instructor-scroll-inner" ref={tableWrapRef}>
								<div className="instructor-header-row">
									<span>Professor Name</span>
									<span>Rating</span>
									<span>Difficulty</span>
									<span>Ratings</span>
								</div>
								{visibleProfessors.map((p) => (
									<div key={p.slug} className="instructor-row">
										<span>
											<Link
												to={`/professors/${p.slug}`}
												state={{ fromPage: { label: `${course.code} – ${course.name}`, url: `/courses/${code}` } }}
											>
												{p.name}
											</Link>
										</span>
										<span>{p.rating != null ? p.rating.toFixed(2) : '—'}</span>
										<span>{p.difficulty != null ? p.difficulty.toFixed(2) : '—'}</span>
										<span>{p.numRatings.toLocaleString()}</span>
									</div>
								))}
							</div>
						</div>
					)}
					{hasExpandable && (
						<div className="course-expand-controls">
							<button type="button" className="course-expand-btn" disabled={!canCollapse}
								onClick={() => setVisibleCount(INITIAL_PROFESSORS_VISIBLE)}>
								<span className="course-expand-chevron up" />
							</button>
							<button type="button" className="course-expand-btn" disabled={!hasMore}
								onClick={() => setVisibleCount((prev) => Math.min(prev + PROFESSORS_VISIBLE_STEP, professors.length))}>
								<span className="course-expand-chevron down" />
							</button>
						</div>
					)}
				</section>
			</div>
			<button
				className={`back-to-top ${showBackToTop ? 'visible' : ''}`}
				onClick={() => window.scrollTo({ top: 0, behavior: 'smooth' })}
				aria-label="Back to top"
			>
				<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round">
					<polyline points="18 15 12 9 6 15" />
				</svg>
			</button>
			<Footer />
		</div>
	);
};

function StatCard({ label, value }: { label: string; value: string }) {
	return (
		<article className="course-stat-card">
			<strong className="course-stat-value">{value}</strong>
			<span className="course-stat-label">{label}</span>
		</article>
	);
}

function DifficultyStatCard({ value }: { value: number | null }) {
	const color = value == null ? '#eee'
		: value <= 1.5 ? '#27ae60'
		: value <= 2.5 ? '#66bd63'
		: value <= 3.0 ? '#f39c12'
		: value <= 3.5 ? '#e67e22'
		: value <= 4.0 ? '#e74c3c'
		: '#c0392b';
	return (
		<article className="course-stat-card">
			<strong className="course-stat-value">{value != null ? value.toFixed(2) : '—'}</strong>
			<div className="course-difficulty-bar">
				<div className="course-difficulty-fill" style={{ width: `${((value ?? 0) / 5) * 100}%`, background: color }} />
			</div>
			<span className="course-stat-label">Avg Difficulty</span>
		</article>
	);
}

export default Course;
