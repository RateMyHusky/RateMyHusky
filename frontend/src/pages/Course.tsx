import { useEffect, useRef, useState } from 'react';
import type { CSSProperties } from 'react';
import { Link, useParams } from 'react-router-dom';
import StarRating from '../components/StarRating';
import NotFound from './NotFound';
import LoadError from '../components/LoadError';
import { fetchCourseData } from '../api/api';
import type { CourseDetail, CourseHistory, HistoryCourseLink } from '../api/api';
import Footer from '../components/Footer';
import { getInitials, stripPrefix } from '../utils/nameUtils';
import { photoThumb, thumbOnError } from '../utils/photoThumb';
import Breadcrumbs from '../components/Breadcrumbs';
import Seo from '../components/Seo';
import BookmarkButton from '../components/BookmarkButton';
import { SHOW_SURVEY_STATS } from '../config';
import FitText from '../components/FitText';
import { relativeTerm, seasonYear } from '../utils/termUtils';
import './Course.css';

const INITIAL_PROFESSORS_VISIBLE = 5;
const PROFESSORS_VISIBLE_STEP = 5;
const TOP_PROFESSORS = 10;
// "Compare top professors": the most-rated who taught the course this recently.
const COMPARE_PROFESSORS = 3;
const COMPARE_RECENT_YEARS = 3;

/* Slugs for the course page's Compare button: the most-rated professors (professors[] arrives
   sorted by rating count) whose last term is within COMPARE_RECENT_YEARS, topped up from the
   rest when fewer qualify. Only professors with ratings count, since Compare ranks by them. */
function compareSlugs(professors: { slug: string; numRatings: number; lastTerm: string | null }[], now = new Date()): string[] {
	const rated = professors.filter((p) => p.slug && p.numRatings > 0);
	const year = (term: string | null) => Number(term?.match(/\d{4}/)?.[0] ?? 0);
	const recent = rated.filter((p) => year(p.lastTerm) >= now.getFullYear() - COMPARE_RECENT_YEARS + 1);
	const picked = recent.slice(0, COMPARE_PROFESSORS);
	for (const p of rated) {
		if (picked.length >= COMPARE_PROFESSORS) break;
		if (!picked.includes(p)) picked.push(p);
	}
	return picked.map((p) => p.slug);
}

/* Display names for summary.bySource keys; an unlisted source shows its key. */
const SOURCE_LABELS: Record<string, string> = { rmp: 'RMP' };
const sourceLabel = (source: string) => SOURCE_LABELS[source] ?? source.toUpperCase();

const Course = () => {
	const { code = '' } = useParams<{ code: string }>();
	const [course, setCourse] = useState<CourseDetail | null>(null);
	const [loading, setLoading] = useState(true);
	const [loadError, setLoadError] = useState<'not_found' | 'failed' | null>(null);
	const [visibleCount, setVisibleCount] = useState(INITIAL_PROFESSORS_VISIBLE);
	const [showBackToTop, setShowBackToTop] = useState(false);
	const tableWrapRef = useRef<HTMLDivElement>(null);
	const professorsRef = useRef<HTMLElement>(null);
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
	const history = course.history;
	const recentInstructors = history?.recentInstructors ?? [];
	const fromPage = { label: `${course.code} – ${course.name}`, url: `/courses/${code}` };
	const toCompare = compareSlugs(professors);
	const compareHref = '/compare?' + toCompare.map((slug, i) => `${'abcd'[i]}=${encodeURIComponent(slug)}`).join('&');

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
							<BookmarkButton itemType="course" itemKey={course.code} size="md" className="course-hero-bookmark" label={course.code} />
						</h1>
						{/* Course departments mostly have no /departments page (those are built from
						    professors' departments), so this opens the course list for the department. */}
						<p className="course-dept">
							<Link className="course-dept-link" to={`/courses?dept=${encodeURIComponent(course.department)}`}>{course.department}</Link>
						</p>
					</div>
					{/* Up top, not in "When it's offered": next term is what a student registering looks for first. */}
					{history && history.offeredNow.length > 0 && (
						<div className="course-hero-offered">
							{history.offeredNow.map(t => <span key={t} className="course-catalog-tag course-hero-offered-tag">Offered {t}</span>)}
						</div>
					)}
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
						<span className="course-stat-label" style={{ display: 'block', textAlign: 'center', position: 'relative' }}>
							Overall Rating
							{breakdown.length > 0 && (
								<svg xmlns="http://www.w3.org/2000/svg" width="1em" height="1em" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" style={{ position: 'absolute', top: '50%', transform: 'translateY(-50%)', marginLeft: '4px', opacity: 0.6 }}><circle cx="12" cy="12" r="10" /><path d="M9.09 9a3 3 0 0 1 5.83 1c0 2-3 3-3 3" /><line x1="12" y1="17" x2="12.01" y2="17" /></svg>
							)}
						</span>
						<div className="course-stat-extra"><StarRating rating={summary.rating ?? 0} size="lg" /></div>
						{breakdown.length > 0 && (
							<div className="course-stat-breakdown">
								{breakdown.map(([source, v]) => (
									<span key={source}>{sourceLabel(source)}: {v.rating!.toFixed(2)}</span>
								))}
							</div>
						)}
					</article>
					<DifficultyStatCard value={summary.difficulty} />
					<StatCard
						label="Ratings"
						value={summary.numRatings ? summary.numRatings.toLocaleString() : '—'}
						hint={breakdown.length > 0 ? `from ${breakdown.map(([source]) => sourceLabel(source)).join(' + ')}` : undefined}
					/>
					{/* With no professors the table below is just an empty-state note, so nothing to jump to. */}
					<StatCard
						label="Professors"
						value={professors.length.toLocaleString()}
						hint={professors.length > 0 ? 'View professors ↓' : undefined}
						onClick={professors.length > 0 ? () => professorsRef.current?.scrollIntoView({ behavior: 'smooth' }) : undefined}
					/>
					{history?.lastOffered && (
						<StatCard label="Last Taught" value={seasonYear(history.lastOffered)} text hint={relativeTerm(history.lastOffered) ?? undefined} />
					)}
					{history?.typicalClassSize != null && (
						<StatCard label="Typical Class Size" value={history.typicalClassSize.toLocaleString()} hint="students per section" />
					)}
					{SHOW_SURVEY_STATS && (
						<StatCard label="Avg Hrs / Week" value={summary.hoursPerWeek != null ? `${summary.hoursPerWeek.toFixed(1)}h` : '—'} />
					)}
				</section>

				{history && <OfferingPanel history={history} />}

				{recentInstructors.length > 0 ? (
					<section className="course-panel">
						<div className="course-panel-header">
							<h2>Recent Professors</h2>
						</div>
						<div className="course-top-prof-grid">
							{recentInstructors.map((r) => (
								<ProfCard
									key={r.slug ?? `unmatched-${r.name}`}
									name={r.name}
									imageUrl={r.imageUrl}
									focusX={r.focusX}
									focusY={r.focusY}
									rating={r.rating}
									footerLeft={r.numRatings != null ? `${r.numRatings.toLocaleString()} rating${r.numRatings === 1 ? '' : 's'}` : '—'}
									footerCenter={r.totalComments != null ? `${r.totalComments.toLocaleString()} comment${r.totalComments === 1 ? '' : 's'}` : '—'}
									footerRight={r.wouldTakeAgainPct != null ? `${Math.round(r.wouldTakeAgainPct)}% again` : '—'}
									to={r.slug ? `/professors/${r.slug}` : undefined}
									fromPage={fromPage}
								/>
							))}
						</div>
					</section>
				) : topProfessors.length > 0 && (
					<section className="course-panel">
						<div className="course-panel-header">
							<h2>Most-Rated Professors</h2>
						</div>
						<div className="course-top-prof-grid">
							{topProfessors.map((prof, index) => (
								<ProfCard
									key={prof.slug}
									name={prof.name}
									imageUrl={prof.imageUrl}
									focusX={prof.focusX}
									focusY={prof.focusY}
									rating={prof.rating}
									footerLeft={`${prof.numRatings.toLocaleString()} rating${prof.numRatings === 1 ? '' : 's'}`}
									footerRight={prof.difficulty != null ? `${prof.difficulty.toFixed(1)} difficulty` : '—'}
									rank={index + 1}
									to={`/professors/${prof.slug}`}
									fromPage={fromPage}
								/>
							))}
						</div>
					</section>
				)}

				<section className="course-panel" ref={professorsRef}>
					<div className="course-panel-header course-panel-header--action">
						<h2>Professors</h2>
						{toCompare.length >= 2 && (
							<Link to={compareHref} className="course-compare-btn">
								Compare top {toCompare.length}
							</Link>
						)}
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
									<span>Last Taught</span>
									<span>Avg Class</span>
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
										<span>{p.lastTerm ?? '—'}</span>
										<span>{p.avgClassSize != null ? p.avgClassSize.toLocaleString() : '—'}</span>
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

function StatCard({ label, value, text = false, hint, onClick }: {
	label: string; value: string; text?: boolean; hint?: string; onClick?: () => void;
}) {
	return (
		<article
			className={`course-stat-card${onClick ? ' course-stat-clickable' : ''}`}
			role={onClick ? 'button' : undefined}
			tabIndex={onClick ? 0 : undefined}
			onClick={onClick}
			onKeyDown={onClick && (e => {
				if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onClick(); }
			})}
		>
			<strong className={`course-stat-value${text ? ' course-stat-value--text' : ''}`}>{text ? <FitText>{value}</FitText> : value}</strong>
			<span className="course-stat-label">{label}</span>
			<div className="course-stat-extra">{hint && <span className="course-stat-hint">{hint}</span>}</div>
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
			<span className="course-stat-label">Avg Difficulty</span>
			<div className="course-stat-extra">
				<div className="course-difficulty-bar">
					<div className="course-difficulty-fill" style={{ width: `${((value ?? 0) / 5) * 100}%`, background: color }} />
				</div>
			</div>
		</article>
	);
}

type ProfCardProps = {
	name: string;
	imageUrl: string | null;
	focusX: number;
	focusY: number;
	rating: number | null;
	footerLeft: string;
	/** Recent Professors' middle stat, as on the professor catalog's cards. */
	footerCenter?: string;
	footerRight: string;
	/** Most-Rated numbers its cards; Recent Professors doesn't. */
	rank?: number;
	/** Omitted for an instructor with no profile: the card is not a link. */
	to?: string;
	fromPage: { label: string; url: string };
};

function ProfCard({ name, imageUrl, focusX, focusY, rating, footerLeft, footerCenter, footerRight, rank, to, fromPage }: ProfCardProps) {
	// The URL whose copy and original both failed; held by URL so a reused card retries a new photo
	const [deadPhoto, setDeadPhoto] = useState<string | null>(null);
	const content = (
		<>
			<div className="course-top-prof-photo">
				{imageUrl && deadPhoto !== imageUrl ? (
					<img
						key={imageUrl}
						className="course-top-prof-img"
						src={photoThumb(imageUrl)}
						alt={name}
						style={{ objectPosition: `${focusX}% ${focusY}%` }}
						onError={thumbOnError(imageUrl, () => setDeadPhoto(imageUrl))}
					/>
				) : (
					<div className="course-top-prof-avatar" aria-hidden="true">
						{getInitials(name)}
					</div>
				)}
				{rank != null && <span className="course-top-prof-rank">#{rank}</span>}
			</div>
			<div className="course-top-prof-body">
				<div className="course-top-prof-body-top">
					<div className="course-top-prof-rating">
						{rating != null ? (
							<>
								<span className="course-top-prof-avg">{rating.toFixed(1)}</span>
								<StarRating rating={rating} size="sm" />
							</>
						) : (
							<span className="course-top-prof-avg">—</span>
						)}
					</div>
					<h3 className="course-top-prof-name">
						{stripPrefix(name)}
					</h3>
				</div>
				<div className="course-top-prof-footer">
					<span>{footerLeft}</span>
					{footerCenter != null && <span className="course-top-prof-footer--center">{footerCenter}</span>}
					<span className="course-top-prof-footer--right">{footerRight}</span>
				</div>
			</div>
		</>
	);
	return to ? (
		<Link to={to} state={{ fromPage }} className="course-top-prof-card" aria-label={`View ${name}`}>
			{content}
		</Link>
	) : (
		<div className="course-top-prof-card course-top-prof-card--static">{content}</div>
	);
}

type OfferingYears = NonNullable<CourseHistory['offeringYears']>;
type SeasonKey = Exclude<keyof OfferingYears, 'window' | 'first'>;
const TILES: [SeasonKey, string][] = [
	['fall', 'Fall'], ['spring', 'Spring'], ['summer1', 'Summer 1'], ['summer2', 'Summer 2'], ['summer', 'Summer'],
];

/* Banner keys an academic year by the year it ends: 2026 -> "2025–26". */
const schoolYear = (year: number) => `${year - 1}–${String(year).slice(2)}`;

function OfferingPanel({ history }: { history: CourseHistory }) {
	const oy = history.offeringYears;
	/* A row from before the scraper stored the years shows the pattern alone. */
	let body = null;
	let pattern = history.pattern;
	if (oy && oy.window.length > 0) {
		const years = oy.window;
		const last = years[years.length - 1];
		/* "N of M": M counts only the years since the course existed. */
		const existed = years.filter((y) => y >= oy.first).length;
		/* A full-summer-only course (Summer Full, CPS, Law) didn't skip the halves: hide them. */
		const fullSummerOnly = oy.summer.length > 0 && oy.summer1.length === 0 && oy.summer2.length === 0;
		const tiles = TILES.filter(([k]) => {
			if (k === 'summer') return oy.summer.length > 0;
			if (k === 'summer1' || k === 'summer2') return !fullSummerOnly;
			return true;
		});

		if (oy.first > last) {
			body = <p className="course-offering-note">First offered {history.firstOffered}</p>;
		} else if (TILES.every(([k]) => oy[k].length === 0)) {
			if (history.offeredNow.length > 0) {
				/* Ran only before the window and is back on the schedule now: not "not offered".
				   The note explains the gap, so the header's "Not offered recently" would contradict it. */
				pattern = null;
				body = <p className="course-offering-note">Back for {history.offeredNow.join(' and ')}, after no runs from {schoolYear(years[0])} to {schoolYear(last)}</p>;
			} else {
				body = <p className="course-offering-note">Not offered since {history.lastOffered}</p>;
			}
		} else {
			body = (
				<>
					<div className="course-offering-tiles" style={{ '--tiles': tiles.length } as CSSProperties}>
						{tiles.map(([k, label]) => {
							const ran = oy[k].length;
							const segs = years.map((y) => {
								const state = oy[k].includes(y) ? 'ran' : y < oy.first ? 'before' : 'empty';
								const what = state === 'ran' ? 'ran' : state === 'before' ? 'before this course existed' : 'not offered';
								return { y, state, desc: `${schoolYear(y)}: ${what}` };
							});
							return (
								<div key={k} className={`course-offering-tile${ran === 0 ? ' course-offering-tile--off' : ''}`}>
									<span className="course-offering-tile-label">{label}</span>
									{/* Color and hover titles alone don't reach touch or screen readers. Short year
									    in each segment so five tiles fit a row; the titles carry the full year.
									    Fall is the calendar year before the school year's end year. */}
									<span className="course-offering-bar" role="img" aria-label={`${label}: ${segs.map((s) => s.desc).join(', ')}`}>
										{segs.map((s) => (
											<span key={s.y} className={`course-offering-seg course-offering-seg--${s.state}`} title={s.desc}>’{String(k === 'fall' ? s.y - 1 : s.y).slice(2)}</span>
										))}
									</span>
									<span className="course-offering-count">
										{ran === 0 ? 'Not offered' : `${ran} of ${existed} ${existed === 1 ? 'year' : 'years'}`}
									</span>
								</div>
							);
						})}
					</div>
					{years[0] < oy.first && <p className="course-offering-caption">Striped: before this course existed</p>}
				</>
			);
		}
	}

	return (
		<section className="course-panel">
			<div className="course-panel-header course-offering-header">
				<h2>When it's offered</h2>
				{pattern && <span className="course-offering-pattern">{pattern}</span>}
			</div>
			{body}
			{history.replacedBy && <SuccessorLine verb="Replaced by" link={history.replacedBy} />}
			{history.replaces && <SuccessorLine verb="Replaced" link={history.replaces} />}
		</section>
	);
}

function SuccessorLine({ verb, link }: { verb: string; link: HistoryCourseLink }) {
	const label = link.name ? `${link.code} (${link.name})` : link.code;
	return (
		<p className="course-offering-successor">
			{verb}{' '}
			{link.hasPage ? <Link to={`/courses/${link.code.toLowerCase()}`}>{label}</Link> : label}
			{' '}in {link.since}
		</p>
	);
}

export default Course;
