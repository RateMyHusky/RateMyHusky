import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { fetchProfessorData, fetchProfessorsCatalog, fetchSearchSuggestions } from '../api/api';
import { useAuth } from '../context/AuthContext';
import { termSortKey } from '../utils/termUtils';
import type { CatalogProfessor, ProfessorProfile, ProfessorSuggestion } from '../api/api';
import StarRating from '../components/StarRating';
import Footer from '../components/Footer';

import './Compare.css';

type Side = 'a' | 'b';

interface TraceSnapshot {
	term: string;
	course: string;
	score: number;
}

type WinnerSide = 'left' | 'right' | null;

const CATALOG_LIMIT = 10000;

// Module-level cache so catalog survives component unmounts
let cachedCatalog: CatalogProfessor[] | null = null;

const slugify = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

const normalizeName = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '');

const getInitials = (name: string) =>
	name
		.split(/\s+/)
		.filter(Boolean)
		.slice(0, 2)
		.map((part) => part[0]?.toUpperCase() ?? '')
		.join('');

const parseMaybeNumber = (value: number | null | undefined) => {
	if (typeof value !== 'number' || Number.isNaN(value)) return null;
	return value;
};

const formatMetric = (value: number | null | undefined, digits = 2) => {
	const parsed = parseMaybeNumber(value);
	return parsed === null ? '—' : parsed.toFixed(digits);
};

const getDifficultyClass = (value: number | null | undefined) => {
	const d = parseMaybeNumber(value);
	if (d === null) return 'compare-value-muted';
	if (d <= 2.5) return 'compare-value-good';
	if (d <= 3.5) return 'compare-value-mid';
	return 'compare-value-hard';
};

const pickWinner = (
	leftValue: number | null | undefined,
	rightValue: number | null | undefined,
	mode: 'higher' | 'lower' = 'higher',
	decimals = 2,
): WinnerSide => {
	const left = parseMaybeNumber(leftValue);
	const right = parseMaybeNumber(rightValue);

	if (left === null && right === null) return null;
	if (left === null) return 'right';
	if (right === null) return 'left';

	// Round to displayed precision so ties match what the user sees
	const factor = 10 ** decimals;
	const l = Math.round(left * factor) / factor;
	const r = Math.round(right * factor) / factor;
	if (l === r) return null;

	if (mode === 'higher') return l > r ? 'left' : 'right';
	return l < r ? 'left' : 'right';
};

const cleanTermTitle = (t: string): string => t.replace(/^\d{6}:\s*/, '').replace(/\s*\d{6}/g, '').trim();

const getRecentTraceSnapshot = (profile: ProfessorProfile | null): TraceSnapshot | null => {
	if (!profile?.traceCourses?.length) return null;

	const sorted = [...profile.traceCourses].sort((a, b) => {
		const ka = termSortKey(a.termTitle);
		const kb = termSortKey(b.termTitle);
		if (ka !== kb) return kb - ka;
		return b.courseId - a.courseId;
	});

	const mostRecent = sorted.find((c) => c.overallRating != null);
	if (!mostRecent || mostRecent.overallRating == null) return null;

	return {
		term: cleanTermTitle(mostRecent.termTitle),
		course: mostRecent.displayName,
		score: mostRecent.overallRating,
	};
};


function Compare() {
	const [searchParams, setSearchParams] = useSearchParams();
	const { user, loading: authLoading } = useAuth();

	const [catalog, setCatalog] = useState<CatalogProfessor[]>([]);
	const [, setCatalogLoading] = useState(true);
	const [catalogError, setCatalogError] = useState<string | null>(null);

	const [leftQuery, setLeftQuery] = useState('');
	const [rightQuery, setRightQuery] = useState('');
	const [leftSuggestions, setLeftSuggestions] = useState<ProfessorSuggestion[]>([]);
	const [rightSuggestions, setRightSuggestions] = useState<ProfessorSuggestion[]>([]);
	const [showLeftSuggestions, setShowLeftSuggestions] = useState(false);
	const [showRightSuggestions, setShowRightSuggestions] = useState(false);
	const [leftActiveIndex, setLeftActiveIndex] = useState(-1);
	const [rightActiveIndex, setRightActiveIndex] = useState(-1);

	const leftWrapperRef = useRef<HTMLDivElement>(null);
	const rightWrapperRef = useRef<HTMLDivElement>(null);
	const leftDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const rightDebounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
	const leftFetchGenRef = useRef(0);
	const rightFetchGenRef = useRef(0);

	const [leftProfile, setLeftProfile] = useState<ProfessorProfile | null>(null);
	const [rightProfile, setRightProfile] = useState<ProfessorProfile | null>(null);
	const [leftLoading, setLeftLoading] = useState(false);
	const [rightLoading, setRightLoading] = useState(false);
	const [leftError, setLeftError] = useState<string | null>(null);
	const [rightError, setRightError] = useState<string | null>(null);

	const leftSlug = searchParams.get('a')?.trim() ?? '';
	const rightSlug = searchParams.get('b')?.trim() ?? '';

	useEffect(() => {
		const oldParam = searchParams.get('prof')?.trim();
		const existingA = searchParams.get('a')?.trim();
		if (!oldParam || existingA) return;

		const next = new URLSearchParams(searchParams);
		next.set('a', oldParam);
		next.delete('prof');
		setSearchParams(next, { replace: true });
	}, [searchParams, setSearchParams]);

	useEffect(() => {
		if (cachedCatalog) {
			setCatalog(cachedCatalog);
			return;
		}

		let cancelled = false;

		const loadCatalog = async () => {
			try {
				setCatalogLoading(true);
				setCatalogError(null);
				const result = await fetchProfessorsCatalog({ sort: 'alpha', limit: CATALOG_LIMIT, page: 1 });
				if (!cancelled) {
					cachedCatalog = result.professors;
					setCatalog(result.professors);
				}
			} catch {
				if (!cancelled) {
					setCatalogError('Could not load professor list. Please refresh and try again.');
				}
			} finally {
				if (!cancelled) setCatalogLoading(false);
			}
		};

		loadCatalog();
		return () => {
			cancelled = true;
		};
	}, []);

	const catalogBySlug = useMemo(() => {
		const map = new Map<string, CatalogProfessor>();
		catalog.forEach((prof) => {
			map.set(prof.slug, prof);
		});
		return map;
	}, [catalog]);

	const leftCatalogProfessor = leftSlug ? catalogBySlug.get(leftSlug) ?? null : null;
	const rightCatalogProfessor = rightSlug ? catalogBySlug.get(rightSlug) ?? null : null;

	useEffect(() => {
		if (!leftSlug || leftCatalogProfessor) return;
		setLeftError('That professor could not be found in the catalog.');
	}, [leftSlug, leftCatalogProfessor]);

	useEffect(() => {
		if (!rightSlug || rightCatalogProfessor) return;
		setRightError('That professor could not be found in the catalog.');
	}, [rightSlug, rightCatalogProfessor]);

	useEffect(() => {
		if (!leftSlug) {
			setLeftQuery('');
		} else if (leftCatalogProfessor?.name) {
			setLeftQuery(leftCatalogProfessor.name);
		}
		setLeftSuggestions([]);
		setShowLeftSuggestions(false);
		setLeftActiveIndex(-1);
	}, [leftSlug, leftCatalogProfessor?.name]);

	useEffect(() => {
		if (!rightSlug) {
			setRightQuery('');
		} else if (rightCatalogProfessor?.name) {
			setRightQuery(rightCatalogProfessor.name);
		}
		setRightSuggestions([]);
		setShowRightSuggestions(false);
		setRightActiveIndex(-1);
	}, [rightSlug, rightCatalogProfessor?.name]);

	useEffect(() => {
		let cancelled = false;

		const load = async () => {
			if (!leftSlug) {
				setLeftProfile(null);
				setLeftError(null);
				return;
			}
			setLeftLoading(true);
			setLeftError(null);
			const profile = await fetchProfessorData(leftSlug);
			if (cancelled) return;
			if (!profile) {
				setLeftProfile(null);
				setLeftError('Could not load this professor profile.');
			} else {
				setLeftProfile(profile);
			}
			setLeftLoading(false);
		};

		load();
		return () => {
			cancelled = true;
		};
	}, [leftSlug, user]);

	useEffect(() => {
		let cancelled = false;

		const load = async () => {
			if (!rightSlug) {
				setRightProfile(null);
				setRightError(null);
				return;
			}
			setRightLoading(true);
			setRightError(null);
			const profile = await fetchProfessorData(rightSlug);
			if (cancelled) return;
			if (!profile) {
				setRightProfile(null);
				setRightError('Could not load this professor profile.');
			} else {
				setRightProfile(profile);
			}
			setRightLoading(false);
		};

		load();
		return () => {
			cancelled = true;
		};
	}, [rightSlug, user]);

	const updateSlugs = (updates: { a?: string; b?: string }) => {
		const next = new URLSearchParams(searchParams);

		if (updates.a !== undefined) {
			if (updates.a) next.set('a', updates.a);
			else next.delete('a');
		}

		if (updates.b !== undefined) {
			if (updates.b) next.set('b', updates.b);
			else next.delete('b');
		}

		next.delete('prof');
		const nextString = next.toString();
		if (nextString === searchParams.toString()) return;
		setSearchParams(next, { replace: true });
	};

	const handlePick = (side: Side, slug: string) => {
		if (side === 'a') {
			if (slug === rightSlug) return;
			updateSlugs({ a: slug });
			return;
		}
		if (slug === leftSlug) return;
		updateSlugs({ b: slug });
	};

	const handleClear = (side: Side) => {
		if (side === 'a') {
			setLeftQuery('');
			setLeftSuggestions([]);
			setShowLeftSuggestions(false);
			setLeftActiveIndex(-1);
			updateSlugs({ a: '' });
			return;
		}

		setRightQuery('');
		setRightSuggestions([]);
		setShowRightSuggestions(false);
		setRightActiveIndex(-1);
		updateSlugs({ b: '' });
	};

	const getSlugForSuggestion = (name: string) => {
		const lowered = name.toLowerCase();
		const exactMatch = catalog.find((prof) => prof.name.toLowerCase() === lowered);
		if (exactMatch) return exactMatch.slug;

		const normalized = normalizeName(name);
		const normalizedMatch = catalog.find((prof) => normalizeName(prof.name) === normalized);
		if (normalizedMatch) return normalizedMatch.slug;

		return slugify(name);
	};

	const getSuggestionSlug = (suggestion: ProfessorSuggestion) => suggestion.slug || getSlugForSuggestion(suggestion.name);

	const handleSelectSuggestion = (side: Side, suggestion: ProfessorSuggestion) => {
		const selectedSlug = getSuggestionSlug(suggestion);
		if (side === 'a') {
			if (selectedSlug === rightSlug) return;
			setLeftQuery(suggestion.name);
			setShowLeftSuggestions(false);
			setLeftActiveIndex(-1);
			handlePick('a', selectedSlug);
			return;
		}

		if (selectedSlug === leftSlug) return;
		setRightQuery(suggestion.name);
		setShowRightSuggestions(false);
		setRightActiveIndex(-1);
		handlePick('b', selectedSlug);
	};

	useEffect(() => {
		if (leftDebounceRef.current) clearTimeout(leftDebounceRef.current);

		const trimmedQuery = leftQuery.trim();
		if (trimmedQuery.length < 2) {
			setLeftSuggestions([]);
			setShowLeftSuggestions(false);
			setLeftActiveIndex(-1);
			return;
		}

		leftFetchGenRef.current += 1;
		const gen = leftFetchGenRef.current;
		leftDebounceRef.current = setTimeout(async () => {
			try {
				const results = await fetchSearchSuggestions(trimmedQuery, 'Professor');
				if (gen !== leftFetchGenRef.current) return;
				const professorResults = results
					.filter((result): result is ProfessorSuggestion => result.type === 'professor')
					.filter((result) => getSuggestionSlug(result) !== rightSlug)
					.slice(0, 3);

				setLeftSuggestions(professorResults);
				setShowLeftSuggestions(professorResults.length > 0);
				setLeftActiveIndex(-1);
			} catch {
				if (gen !== leftFetchGenRef.current) return;
				setLeftSuggestions([]);
				setShowLeftSuggestions(false);
			}
		}, 200);

		return () => {
			if (leftDebounceRef.current) clearTimeout(leftDebounceRef.current);
		};
	}, [leftQuery, rightSlug, catalog]);

	useEffect(() => {
		if (rightDebounceRef.current) clearTimeout(rightDebounceRef.current);

		const trimmedQuery = rightQuery.trim();
		if (trimmedQuery.length < 2) {
			setRightSuggestions([]);
			setShowRightSuggestions(false);
			setRightActiveIndex(-1);
			return;
		}

		rightFetchGenRef.current += 1;
		const gen = rightFetchGenRef.current;
		rightDebounceRef.current = setTimeout(async () => {
			try {
				const results = await fetchSearchSuggestions(trimmedQuery, 'Professor');
				if (gen !== rightFetchGenRef.current) return;
				const professorResults = results
					.filter((result): result is ProfessorSuggestion => result.type === 'professor')
					.filter((result) => getSuggestionSlug(result) !== leftSlug)
					.slice(0, 3);

				setRightSuggestions(professorResults);
				setShowRightSuggestions(professorResults.length > 0);
				setRightActiveIndex(-1);
			} catch {
				if (gen !== rightFetchGenRef.current) return;
				setRightSuggestions([]);
				setShowRightSuggestions(false);
			}
		}, 200);

		return () => {
			if (rightDebounceRef.current) clearTimeout(rightDebounceRef.current);
		};
	}, [rightQuery, leftSlug, catalog]);

	useEffect(() => {
		const handleOutsideClick = (event: MouseEvent) => {
			if (leftWrapperRef.current && !leftWrapperRef.current.contains(event.target as Node)) {
				setShowLeftSuggestions(false);
			}
			if (rightWrapperRef.current && !rightWrapperRef.current.contains(event.target as Node)) {
				setShowRightSuggestions(false);
			}
		};

		document.addEventListener('mousedown', handleOutsideClick);
		return () => document.removeEventListener('mousedown', handleOutsideClick);
	}, []);

	const leftSnapshot = getRecentTraceSnapshot(leftProfile);
	const rightSnapshot = getRecentTraceSnapshot(rightProfile);

	const leftRmp = leftProfile?.rmpRating ?? leftCatalogProfessor?.rmpRating ?? null;
	const rightRmp = rightProfile?.rmpRating ?? rightCatalogProfessor?.rmpRating ?? null;
	const leftTrace = leftProfile?.traceRating ?? leftCatalogProfessor?.traceRating ?? null;
	const rightTrace = rightProfile?.traceRating ?? rightCatalogProfessor?.traceRating ?? null;

	const leftDept = leftCatalogProfessor
		? `${leftCatalogProfessor.department} (${leftCatalogProfessor.college})`
		: leftProfile?.department
			? leftProfile.department
			: '—';
	const rightDept = rightCatalogProfessor
		? `${rightCatalogProfessor.department} (${rightCatalogProfessor.college})`
		: rightProfile?.department
			? rightProfile.department
			: '—';

	const compareRows = [
		{
			label: 'Department',
			left: leftDept,
			right: rightDept,
			winner: null,
			weight: 0,
		},
		{
			label: 'Overall Rating',
			left: formatMetric(leftProfile?.avgRating ?? leftCatalogProfessor?.avgRating),
			right: formatMetric(rightProfile?.avgRating ?? rightCatalogProfessor?.avgRating),
			winner: pickWinner(leftProfile?.avgRating ?? leftCatalogProfessor?.avgRating, rightProfile?.avgRating ?? rightCatalogProfessor?.avgRating),
			weight: 3,
		},
		{
			label: 'RMP Rating',
			left: formatMetric(leftRmp),
			right: formatMetric(rightRmp),
			winner: pickWinner(leftRmp, rightRmp),
			weight: 2,
		},
		{
			label: 'Student Rating',
			left: formatMetric(leftTrace),
			right: formatMetric(rightTrace),
			winner: pickWinner(leftTrace, rightTrace),
			weight: 2,
		},
		{
			label: 'Difficulty',
			left: formatMetric(leftProfile?.difficulty),
			right: formatMetric(rightProfile?.difficulty),
			leftClass: getDifficultyClass(leftProfile?.difficulty),
			rightClass: getDifficultyClass(rightProfile?.difficulty),
			winner: pickWinner(leftProfile?.difficulty, rightProfile?.difficulty, 'lower'),
			weight: 1.5,
		},
		{
			label: 'Total Reviews',
			left: leftProfile?.totalComments?.toLocaleString() ?? leftCatalogProfessor?.totalComments?.toLocaleString() ?? '—',
			right: rightProfile?.totalComments?.toLocaleString() ?? rightCatalogProfessor?.totalComments?.toLocaleString() ?? '—',
			winner: pickWinner(leftProfile?.totalComments ?? leftCatalogProfessor?.totalComments, rightProfile?.totalComments ?? rightCatalogProfessor?.totalComments, 'higher', 0),
			weight: 0.5,
		},
		{
			label: 'Would Take Again',
			left:
				leftProfile?.wouldTakeAgainPct === null || leftProfile?.wouldTakeAgainPct === undefined
					? '—'
					: `${leftProfile.wouldTakeAgainPct.toFixed(0)}%`,
			right:
				rightProfile?.wouldTakeAgainPct === null || rightProfile?.wouldTakeAgainPct === undefined
					? '—'
					: `${rightProfile.wouldTakeAgainPct.toFixed(0)}%`,
			winner: pickWinner(leftProfile?.wouldTakeAgainPct, rightProfile?.wouldTakeAgainPct, 'higher', 0),
			weight: 2,
		},
		{
			label: 'Recent Student Review Snapshot',
			left: leftSnapshot
				? `${leftSnapshot.score.toFixed(2)} (${leftSnapshot.term})`
				: user
					? '—'
					: 'Sign in to view student reviews',
			right: rightSnapshot
				? `${rightSnapshot.score.toFixed(2)} (${rightSnapshot.term})`
				: user
					? '—'
					: 'Sign in to view student reviews',
			footnoteLeft: leftSnapshot?.course,
			footnoteRight: rightSnapshot?.course,
			winner: pickWinner(leftSnapshot?.score, rightSnapshot?.score),
			weight: 1.5,
		},
	];

	const bothSelected = Boolean(leftSlug) && Boolean(rightSlug);
	const bothReady = bothSelected && !leftLoading && !rightLoading;

	const recommendation = (() => {
		if (!bothReady || !leftProfile || !rightProfile) return null;

		let leftScore = 0;
		let rightScore = 0;
		const leftKeyWins: string[] = [];
		const rightKeyWins: string[] = [];

		for (const row of compareRows) {
			if (!row.weight || row.winner === null) continue;
			if (row.winner === 'left') {
				leftScore += row.weight;
				if (row.weight >= 2) leftKeyWins.push(row.label);
			} else {
				rightScore += row.weight;
				if (row.weight >= 2) rightKeyWins.push(row.label);
			}
		}

		if (leftScore === 0 && rightScore === 0) return null;

		const leftName = leftCatalogProfessor?.name ?? leftProfile.name ?? 'Professor A';
		const rightName = rightCatalogProfessor?.name ?? rightProfile.name ?? 'Professor B';

		if (leftScore > rightScore) {
			return { winner: 'left' as const, name: leftName, otherName: rightName, keyWins: leftKeyWins };
		} else if (rightScore > leftScore) {
			return { winner: 'right' as const, name: rightName, otherName: leftName, keyWins: rightKeyWins };
		} else {
			return { winner: 'tie' as const, leftName, rightName };
		}
	})();

	const renderProfileCard = (
		slug: string,
		catalogProf: CatalogProfessor | null,
		profile: ProfessorProfile | null,
		isLoading: boolean,
		error: string | null,
		slotLabel: string,
	) => {
		if (isLoading) return <p className="compare-status">Loading profile...</p>;
		if (error && !profile && !catalogProf) return <p className="compare-status compare-status-error">{error}</p>;

		const source = catalogProf || profile;
		if (!source) return <p className="compare-status">Pick a professor for slot {slotLabel}.</p>;

		const name = catalogProf?.name ?? profile?.name ?? '';
		const dept = catalogProf?.department ?? profile?.department ?? '';
		const imgUrl = profile?.imageUrl ?? catalogProf?.imageUrl ?? null;
		const rating = profile?.avgRating ?? catalogProf?.avgRating ?? null;
		const profSlug = catalogProf?.slug ?? slug;

		return (
			<>
				<div className="compare-avatar-wrap">
					{imgUrl ? (
						<>
							<img
								src={imgUrl}
								alt={name}
								className="compare-avatar-img"
								onError={(e) => {
									e.currentTarget.style.display = 'none';
									const fb = e.currentTarget.parentElement?.querySelector('.compare-avatar-fallback') as HTMLElement;
									if (fb) fb.style.display = 'flex';
								}}
							/>
							<div className="compare-avatar-fallback" style={{ display: 'none' }}>{getInitials(name)}</div>
						</>
					) : (
						<div className="compare-avatar-fallback">{getInitials(name)}</div>
					)}
				</div>
				<h3>{name}</h3>
				<p>{dept}</p>
				<div className="compare-rating-line">
					<strong>{formatMetric(rating)}</strong>
					<StarRating rating={rating ?? 0} size="sm" />
				</div>
				<Link
					className="compare-profile-link"
					to={`/professors/${profSlug}`}
					state={{ fromPage: { label: 'Compare', url: `/compare?${searchParams.toString()}` } }}
				>
					View profile
				</Link>
			</>
		);
	};

	return (
		<>
			<main className="compare-page">
			<section className="compare-hero">
				<div className="compare-hero-inner">
					<p className="compare-kicker">Professor Compare</p>
					<h1>Side-by-side comparison</h1>
					<p className="compare-subtitle">
						Pick two professors and compare rating quality, difficulty, review volume, and recent student review performance.
					</p>
				</div>
			</section>

			<section className="compare-controls" aria-label="Professor selection">
				<div className="compare-control-card" ref={leftWrapperRef}>
					<div className="compare-control-title-row">
						<h2>Professor A</h2>
						{leftSlug && (
							<button className="compare-inline-btn" onClick={() => handleClear('a')}>
								Clear
							</button>
						)}
					</div>
					<input
						className="compare-search"
						placeholder="Search professor name or department"
						value={leftQuery}
						onChange={(e) => {
							setLeftQuery(e.target.value);
							if (e.target.value.trim().length < 2) {
								setLeftSuggestions([]);
								setShowLeftSuggestions(false);
							}
						}}
						onFocus={() => {
							if (leftSuggestions.length > 0) setShowLeftSuggestions(true);
						}}
						onKeyDown={(e) => {
							if (!showLeftSuggestions || leftSuggestions.length === 0) return;

							if (e.key === 'ArrowDown') {
								e.preventDefault();
								setLeftActiveIndex((prev) => (prev < leftSuggestions.length - 1 ? prev + 1 : 0));
							} else if (e.key === 'ArrowUp') {
								e.preventDefault();
								setLeftActiveIndex((prev) => (prev > 0 ? prev - 1 : leftSuggestions.length - 1));
							} else if (e.key === 'Enter' && leftActiveIndex >= 0) {
								e.preventDefault();
								handleSelectSuggestion('a', leftSuggestions[leftActiveIndex]);
							} else if (e.key === 'Escape') {
								setShowLeftSuggestions(false);
							}
						}}
						aria-label="Search left professor"
					/>
					{showLeftSuggestions && (
						<div className="compare-suggestion-list">
							{leftSuggestions.map((prof, index) => {
								const profSlug = getSuggestionSlug(prof);
								return (
									<button
										key={prof.name}
										className={`compare-suggestion ${leftSlug === profSlug || leftActiveIndex === index ? 'active' : ''}`}
										onClick={() => handleSelectSuggestion('a', prof)}
										type="button"
									>
										<span className="compare-suggestion-main">{prof.name}</span>
										<span className="compare-suggestion-meta">
											{prof.dept} • {prof.rating !== null ? prof.rating.toFixed(2) : '—'}
										</span>
									</button>
								);
							})}
						</div>
					)}
				</div>

				<div className="compare-control-card" ref={rightWrapperRef}>
					<div className="compare-control-title-row">
						<h2>Professor B</h2>
						{rightSlug && (
							<button className="compare-inline-btn" onClick={() => handleClear('b')}>
								Clear
							</button>
						)}
					</div>
					<input
						className="compare-search"
						placeholder="Search professor name or department"
						value={rightQuery}
						onChange={(e) => {
							setRightQuery(e.target.value);
							if (e.target.value.trim().length < 2) {
								setRightSuggestions([]);
								setShowRightSuggestions(false);
							}
						}}
						onFocus={() => {
							if (rightSuggestions.length > 0) setShowRightSuggestions(true);
						}}
						onKeyDown={(e) => {
							if (!showRightSuggestions || rightSuggestions.length === 0) return;

							if (e.key === 'ArrowDown') {
								e.preventDefault();
								setRightActiveIndex((prev) => (prev < rightSuggestions.length - 1 ? prev + 1 : 0));
							} else if (e.key === 'ArrowUp') {
								e.preventDefault();
								setRightActiveIndex((prev) => (prev > 0 ? prev - 1 : rightSuggestions.length - 1));
							} else if (e.key === 'Enter' && rightActiveIndex >= 0) {
								e.preventDefault();
								handleSelectSuggestion('b', rightSuggestions[rightActiveIndex]);
							} else if (e.key === 'Escape') {
								setShowRightSuggestions(false);
							}
						}}
						aria-label="Search right professor"
					/>
					{showRightSuggestions && (
						<div className="compare-suggestion-list">
							{rightSuggestions.map((prof, index) => {
								const profSlug = getSuggestionSlug(prof);
								return (
									<button
										key={prof.name}
										className={`compare-suggestion ${rightSlug === profSlug || rightActiveIndex === index ? 'active' : ''}`}
										onClick={() => handleSelectSuggestion('b', prof)}
										type="button"
									>
										<span className="compare-suggestion-main">{prof.name}</span>
										<span className="compare-suggestion-meta">
											{prof.dept} • {prof.rating !== null ? prof.rating.toFixed(2) : '—'}
										</span>
									</button>
								);
							})}
						</div>
					)}
				</div>
			</section>

			{catalogError && <p className="compare-status compare-status-error">{catalogError}</p>}

			<section className="compare-panels" aria-live="polite">
				<article className="compare-profile-card">
					{renderProfileCard(leftSlug, leftCatalogProfessor, leftProfile, leftLoading, leftError, 'A')}
				</article>

				<article className="compare-profile-card">
					{renderProfileCard(rightSlug, rightCatalogProfessor, rightProfile, rightLoading, rightError, 'B')}
				</article>
			</section>

			<section className="compare-metrics">
				<header className="compare-metrics-header">
					<h2>Key Comparison Metrics</h2>
					{bothSelected && !bothReady && <p>Loading comparison...</p>}
				</header>

				<div className="compare-table" role="table" aria-label="Professor metrics comparison table">
					{compareRows.map((row) => {
						const showLeft = Boolean(leftSlug) && !leftLoading;
						const showRight = Boolean(rightSlug) && !rightLoading;
						const renderValue = (value: string, showValue: boolean) => {
							if (!authLoading && showValue && row.label === 'Recent Student Review Snapshot' && value === 'Sign in to view student reviews') {
								return (
									<span className="compare-lock-prompt">
										<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="compare-lock-icon">
											<rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
											<path d="M7 11V7a5 5 0 0 1 10 0v4" />
										</svg>
										<span>Sign in with your <span className="husky-email">husky.neu.edu</span> account to view</span>
									</span>
								);
							}

							return <span>{showValue ? value : '—'}</span>;
						};
						return (
							<div className="compare-row" role="row" key={row.label}>
								<div
									className={`compare-cell compare-cell-left ${showLeft ? (row.leftClass ?? '') : ''} ${bothSelected && showLeft && row.winner === 'left' ? 'compare-cell-winner' : ''}`}
									role="cell"
								>
									{renderValue(row.left, showLeft)}
									{showLeft && row.footnoteLeft && <small>{row.footnoteLeft}</small>}
								</div>
								<div className="compare-cell compare-cell-label" role="columnheader">
									{row.label}
								</div>
								<div
									className={`compare-cell compare-cell-right ${showRight ? (row.rightClass ?? '') : ''} ${bothSelected && showRight && row.winner === 'right' ? 'compare-cell-winner' : ''}`}
									role="cell"
								>
									{renderValue(row.right, showRight)}
									{showRight && row.footnoteRight && <small>{row.footnoteRight}</small>}
								</div>
							</div>
						);
					})}
				</div>
			</section>

		{recommendation && (
			<section className="compare-verdict">
				<div className="compare-verdict-inner">
					{recommendation.winner === 'tie' ? (
						<>
							<p className="compare-verdict-title">It's a tie</p>
							<p className="compare-verdict-body">
								{recommendation.leftName} and {recommendation.rightName} are evenly matched
								across the key metrics. Both are solid choices, so consider factors like course availability or teaching style.
							</p>
						</>
					) : (
						<>
							<p className="compare-verdict-kicker">Our Recommendation</p>
							<p className="compare-verdict-title">{recommendation.name}</p>
							<p className="compare-verdict-body">
								{recommendation.keyWins.length > 0
									? `${recommendation.name} has the edge in ${recommendation.keyWins.join(', ')}, making them the stronger overall choice.`
									: `${recommendation.name} comes out ahead based on the available data.`}
							</p>
						</>
					)}
				</div>
			</section>
		)}

			</main>
			<Footer />
		</>
	);
}

export default Compare;
