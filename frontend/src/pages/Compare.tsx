import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { fetchProfessorData, fetchProfessorsCatalog, fetchSearchSuggestions } from '../api/api';
import { useAuth } from '../context/AuthContext';
import { termSortKey } from '../utils/termUtils';
import type { CatalogProfessor, ProfessorProfile, ProfessorSuggestion } from '../api/api';
import StarRating from '../components/StarRating';
import Footer from '../components/Footer';

import './Compare.css';

/* ---- Slot config ----
   Each slot maps to a URL param: /compare?a=slug&b=slug&c=slug&d=slug */
const SLOT_KEYS = ['a', 'b', 'c', 'd'] as const;
const SLOT_LABELS = ['A', 'B', 'C', 'D'] as const;
const MAX_SLOTS = SLOT_KEYS.length;
const MIN_OPEN_SLOTS = 2; // A and B always show a search box

const CATALOG_LIMIT = 10000;
const SIGN_IN_SENTINEL = '__sign_in__';
const NUMBER_WORDS = ['zero', 'one', 'two', 'three', 'four'];

// Module-level cache so catalog survives component unmounts
let cachedCatalog: CatalogProfessor[] | null = null;

interface TraceSnapshot {
	term: string;
	course: string;
	score: number;
}

interface ProfileEntry {
	status: 'loading' | 'ready' | 'error';
	profile: ProfessorProfile | null;
}

interface SlotData {
	index: number;
	label: string;
	slug: string;
	catalogProf: CatalogProfessor | null;
	profile: ProfessorProfile | null;
	loading: boolean;
	failed: boolean;
	name: string;
}

interface CompareRow {
	label: string;
	values: string[];
	footnotes?: (string | undefined)[];
	winner: number | null; // slot index, or null for no winner
	weight: number;
}

/* ---- Helpers ---- */
const normalizeName = (value: string) => value.toLowerCase().replace(/[^a-z0-9]/g, '');

const parseMaybeNumber = (value: number | null | undefined) => {
	if (typeof value !== 'number' || Number.isNaN(value)) return null;
	return value;
};

const formatMetric = (value: number | null | undefined, digits = 2) => {
	const parsed = parseMaybeNumber(value);
	return parsed === null ? '—' : parsed.toFixed(digits);
};

/* Picks the single best slot among those that have a value.
   Needs at least two values to compare, and returns null on a tie for first. */
const pickWinnerIndex = (
	values: (number | null | undefined)[],
	mode: 'higher' | 'lower' = 'higher',
	decimals = 2,
): number | null => {
	const factor = 10 ** decimals;
	const valid = values
		.map((value, index) => {
			const parsed = parseMaybeNumber(value);
			// Round to displayed precision so ties match what the user sees
			return parsed === null ? null : { index, value: Math.round(parsed * factor) / factor };
		})
		.filter((entry): entry is { index: number; value: number } => entry !== null);

	if (valid.length < 2) return null;

	const nums = valid.map((entry) => entry.value);
	const best = mode === 'higher' ? Math.max(...nums) : Math.min(...nums);
	const top = valid.filter((entry) => entry.value === best);
	return top.length === 1 ? top[0].index : null;
};

const joinNames = (names: string[]) => {
	if (names.length <= 2) return names.join(' and ');
	return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`;
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

/* ---- One search box (replaces the duplicated left/right search code) ---- */
interface ResolvedSuggestion {
	prof: ProfessorSuggestion;
	slug: string;
}

interface SlotSearchProps {
	label: string;
	slug: string;
	selectedName: string | null;
	excludeSlugs: string[];
	resolveSlug: (suggestion: ProfessorSuggestion) => string | null;
	onSelect: (slug: string) => void;
	onClear: () => void;
	clearLabel: string | null;
	autoFocus: boolean;
}

function SlotSearch({
	label,
	slug,
	selectedName,
	excludeSlugs,
	resolveSlug,
	onSelect,
	onClear,
	clearLabel,
	autoFocus,
}: SlotSearchProps) {
	const [query, setQuery] = useState('');
	const [suggestions, setSuggestions] = useState<ResolvedSuggestion[]>([]);
	const [open, setOpen] = useState(false);
	const [activeIndex, setActiveIndex] = useState(-1);

	const wrapperRef = useRef<HTMLDivElement>(null);
	const inputRef = useRef<HTMLInputElement>(null);
	const fetchGenRef = useRef(0);
	const excludeKey = excludeSlugs.join(',');

	useEffect(() => {
		if (autoFocus) inputRef.current?.focus();
	}, [autoFocus]);

	// Keep the input text in sync with the selected professor
	useEffect(() => {
		if (!slug) setQuery('');
		else if (selectedName) setQuery(selectedName);
		setSuggestions([]);
		setOpen(false);
		setActiveIndex(-1);
	}, [slug, selectedName]);

	// Debounced suggestion fetch
	useEffect(() => {
		const trimmed = query.trim();
		if (trimmed.length < 2 || (slug && trimmed === selectedName)) {
			fetchGenRef.current += 1;
			setSuggestions([]);
			setOpen(false);
			setActiveIndex(-1);
			return;
		}

		fetchGenRef.current += 1;
		const gen = fetchGenRef.current;
		const excluded = new Set(excludeKey.split(',').filter(Boolean));

		const timer = setTimeout(async () => {
			try {
				const results = await fetchSearchSuggestions(trimmed, 'Professor');
				if (gen !== fetchGenRef.current) return;
				const professorResults = results
					.filter((result): result is ProfessorSuggestion => result.type === 'professor')
					.map((prof) => ({ prof, slug: resolveSlug(prof) }))
					.filter((entry): entry is ResolvedSuggestion => entry.slug !== null && !excluded.has(entry.slug))
					.slice(0, 3);

				setSuggestions(professorResults);
				setOpen(professorResults.length > 0);
				setActiveIndex(-1);
			} catch {
				if (gen !== fetchGenRef.current) return;
				setSuggestions([]);
				setOpen(false);
			}
		}, 200);

		return () => clearTimeout(timer);
	}, [query, slug, selectedName, excludeKey, resolveSlug]);

	useEffect(() => {
		const handleOutsideClick = (event: MouseEvent) => {
			if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
				setOpen(false);
			}
		};
		document.addEventListener('mousedown', handleOutsideClick);
		return () => document.removeEventListener('mousedown', handleOutsideClick);
	}, []);

	const select = ({ prof, slug: profSlug }: ResolvedSuggestion) => {
		setQuery(prof.name);
		setOpen(false);
		setActiveIndex(-1);
		onSelect(profSlug);
	};

	return (
		<div className={`compare-control-card ${open ? 'is-open' : ''} ${slug ? 'is-filled' : ''}`} ref={wrapperRef}>
			<div className="compare-control-title-row">
				<h2>{label}</h2>
				{clearLabel && (
					<button className="compare-inline-btn" type="button" onClick={onClear}>
						{clearLabel}
					</button>
				)}
			</div>
			<input
				ref={inputRef}
				className="compare-search"
				placeholder="Search professor name or department"
				value={query}
				onChange={(e) => setQuery(e.target.value)}
				onFocus={() => {
					if (suggestions.length > 0) setOpen(true);
				}}
				onKeyDown={(e) => {
					if (!open || suggestions.length === 0) return;

					if (e.key === 'ArrowDown') {
						e.preventDefault();
						setActiveIndex((prev) => (prev < suggestions.length - 1 ? prev + 1 : 0));
					} else if (e.key === 'ArrowUp') {
						e.preventDefault();
						setActiveIndex((prev) => (prev > 0 ? prev - 1 : suggestions.length - 1));
					} else if (e.key === 'Enter' && activeIndex >= 0) {
						e.preventDefault();
						select(suggestions[activeIndex]);
					} else if (e.key === 'Escape') {
						setOpen(false);
					}
				}}
				aria-label={`Search ${label}`}
			/>
			{open && (
				<div className="compare-suggestion-list">
					{suggestions.map((entry, index) => {
						const { prof, slug: profSlug } = entry;
						return (
							<button
								key={profSlug}
								className={`compare-suggestion ${slug === profSlug || activeIndex === index ? 'active' : ''}`}
								onClick={() => select(entry)}
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
	);
}

/* ---- Page ---- */
function Compare() {
	const [searchParams, setSearchParams] = useSearchParams();
	const { user, loading: authLoading } = useAuth();

	const [catalog, setCatalog] = useState<CatalogProfessor[]>(cachedCatalog ?? []);
	const [catalogError, setCatalogError] = useState<string | null>(null);
	const [entries, setEntries] = useState<Record<string, ProfileEntry>>({});
	const [openCount, setOpenCount] = useState(MIN_OPEN_SLOTS);
	const [focusSlot, setFocusSlot] = useState<number | null>(null);

	const slugs = SLOT_KEYS.map((key) => searchParams.get(key)?.trim() ?? '');
	const slugKey = slugs.join('|');
	const lastFilledIndex = slugs.reduce((last, slug, i) => (slug ? i : last), -1);
	const visibleCount = Math.max(openCount, MIN_OPEN_SLOTS, lastFilledIndex + 1);

	// Old links used ?prof=slug. Move it to ?a=slug.
	useEffect(() => {
		const oldParam = searchParams.get('prof')?.trim();
		const existingA = searchParams.get('a')?.trim();
		if (!oldParam || existingA) return;

		const next = new URLSearchParams(searchParams);
		next.set('a', oldParam);
		next.delete('prof');
		setSearchParams(next, { replace: true });
	}, [searchParams, setSearchParams]);

	// If the URL already has c or d filled, keep those slots open
	useEffect(() => {
		setOpenCount((count) => Math.max(count, lastFilledIndex + 1));
	}, [lastFilledIndex]);

	useEffect(() => {
		if (cachedCatalog) return;
		let cancelled = false;

		fetchProfessorsCatalog({ sort: 'alpha', limit: CATALOG_LIMIT, page: 1 })
			.then((result) => {
				if (cancelled) return;
				cachedCatalog = result.professors;
				setCatalog(result.professors);
			})
			.catch(() => {
				if (!cancelled) setCatalogError('Could not load professor list. Please refresh and try again.');
			});

		return () => {
			cancelled = true;
		};
	}, []);

	const catalogBySlug = useMemo(() => {
		const map = new Map<string, CatalogProfessor>();
		catalog.forEach((prof) => map.set(prof.slug, prof));
		return map;
	}, [catalog]);

	// Load a profile for every selected slug. Refetches on sign-in/out for TRACE detail.
	useEffect(() => {
		let cancelled = false;
		const active = Array.from(new Set(slugKey.split('|').filter(Boolean)));

		setEntries((prev) => {
			const next: Record<string, ProfileEntry> = {};
			for (const slug of active) {
				next[slug] = prev[slug]?.status === 'ready' ? prev[slug] : { status: 'loading', profile: null };
			}
			return next;
		});

		active.forEach(async (slug) => {
			const profile = await fetchProfessorData(slug);
			if (cancelled) return;
			setEntries((prev) => ({
				...prev,
				[slug]: profile ? { status: 'ready', profile } : { status: 'error', profile: null },
			}));
		});

		return () => {
			cancelled = true;
		};
	}, [slugKey, user]);

	/* Returns the professor's canonical slug, or null if we can't be sure who it is.
	   The search API should always send a slug. If one is missing, only accept a
	   catalog match that is unique by name (narrowed by department if needed);
	   never guess, because the wrong professor would be compared silently. */
	const resolveSlug = useCallback(
		(suggestion: ProfessorSuggestion): string | null => {
			if (suggestion.slug) return suggestion.slug;

			const target = normalizeName(suggestion.name);
			let matches = catalog.filter((prof) => normalizeName(prof.name) === target);
			if (matches.length > 1 && suggestion.dept) {
				matches = matches.filter((prof) => prof.department === suggestion.dept);
			}
			if (matches.length === 1) return matches[0].slug;

			console.error(
				`[Compare] Search result "${suggestion.name}" has no slug and ${
					matches.length === 0 ? 'no' : 'several'
				} catalog matches. Hiding it so the wrong professor can't be compared.`,
			);
			return null;
		},
		[catalog],
	);

	const updateSlot = (index: number, slug: string) => {
		if (slug && slugs.some((existing, i) => i !== index && existing === slug)) return;

		const next = new URLSearchParams(searchParams);
		if (slug) next.set(SLOT_KEYS[index], slug);
		else next.delete(SLOT_KEYS[index]);
		next.delete('prof');

		if (next.toString() === searchParams.toString()) return;
		setSearchParams(next, { replace: true });
	};

	const openSlot = (index: number) => {
		setOpenCount((count) => Math.max(count, index + 1));
		setFocusSlot(index);
	};

	const closeSlot = (index: number) => {
		setOpenCount(index);
		setFocusSlot(null);
	};

	/* ---- Per-slot data ---- */
	const slots: SlotData[] = slugs.map((slug, index) => {
		const catalogProf = slug ? catalogBySlug.get(slug) ?? null : null;
		const entry = slug ? entries[slug] : undefined;
		const profile = entry?.profile ?? null;
		return {
			index,
			label: SLOT_LABELS[index],
			slug,
			catalogProf,
			profile,
			loading: Boolean(slug) && (!entry || entry.status === 'loading'),
			failed: entry?.status === 'error',
			name: catalogProf?.name ?? profile?.name ?? '',
		};
	});

	const isReady = (slot: SlotData) => Boolean(slot.slug) && !slot.loading;
	const displayName = (slot: SlotData) => slot.name || `Professor ${slot.label}`;
	// "Elena Strange" -> "Elena S." (mobile chips) and "Elena" (mobile table header)
	const chipName = (slot: SlotData) => {
		const parts = slot.name.trim().split(/\s+/).filter(Boolean);
		if (parts.length === 0) return `Prof. ${slot.label}`;
		if (parts.length === 1) return parts[0];
		return `${parts[0]} ${parts[parts.length - 1][0]}.`;
	};
	const firstName = (slot: SlotData) => slot.name.trim().split(/\s+/)[0] || `Prof. ${slot.label}`;

	const overall = slots.map((s) => (isReady(s) ? s.profile?.avgRating ?? s.catalogProf?.avgRating ?? null : null));
	const rmp = slots.map((s) => (isReady(s) ? s.profile?.rmpRating ?? s.catalogProf?.rmpRating ?? null : null));
	const trace = slots.map((s) => (isReady(s) ? s.profile?.traceRating ?? s.catalogProf?.traceRating ?? null : null));
	const difficulty = slots.map((s) => (isReady(s) ? s.profile?.difficulty ?? null : null));
	const reviews = slots.map((s) => (isReady(s) ? s.profile?.totalComments ?? s.catalogProf?.totalComments ?? null : null));
	const takeAgain = slots.map((s) =>
		isReady(s) ? s.profile?.wouldTakeAgainPct ?? s.catalogProf?.wouldTakeAgainPct ?? null : null,
	);
	const snapshots = slots.map((s) => (isReady(s) ? getRecentTraceSnapshot(s.profile) : null));

	const departments = slots.map((s) => {
		if (!isReady(s)) return '—';
		if (s.catalogProf) return `${s.catalogProf.department} (${s.catalogProf.college})`;
		return s.profile?.department || '—';
	});

	const compareRows: CompareRow[] = [
		{ label: 'Department', values: departments, winner: null, weight: 0 },
		{
			label: 'Overall Rating',
			values: overall.map((v) => formatMetric(v)),
			winner: pickWinnerIndex(overall),
			weight: 3,
		},
		{ label: 'RMP Rating', values: rmp.map((v) => formatMetric(v)), winner: pickWinnerIndex(rmp), weight: 2 },
		{ label: 'TRACE Rating', values: trace.map((v) => formatMetric(v)), winner: pickWinnerIndex(trace), weight: 2 },
		{
			label: 'Difficulty',
			values: difficulty.map((v) => formatMetric(v)),
			winner: pickWinnerIndex(difficulty, 'lower'),
			weight: 1.5,
		},
		{
			label: 'Total Reviews',
			values: reviews.map((v) => (v === null ? '—' : v.toLocaleString())),
			winner: pickWinnerIndex(reviews, 'higher', 0),
			weight: 0.5,
		},
		{
			label: 'Would Take Again',
			values: takeAgain.map((v) => (v === null ? '—' : `${v.toFixed(0)}%`)),
			winner: pickWinnerIndex(takeAgain, 'higher', 0),
			weight: 2,
		},
		{
			label: 'Recent TRACE Snapshot',
			values: slots.map((s, i) => {
				if (!isReady(s)) return '—';
				const snap = snapshots[i];
				if (snap) return `${snap.score.toFixed(2)} (${snap.term})`;
				return user ? '—' : SIGN_IN_SENTINEL;
			}),
			footnotes: snapshots.map((snap) => snap?.course),
			winner: pickWinnerIndex(snapshots.map((snap) => snap?.score)),
			weight: 1.5,
		},
	];

	const selectedSlots = slots.filter((s) => s.slug);
	// Mobile hides the search area once every open slot has a professor (chips take over)
	const hasEmptyOpenSlot = slots.slice(0, visibleCount).some((s) => !s.slug);
	const selectedCount = selectedSlots.length;
	const anyLoading = selectedSlots.some((s) => s.loading);
	const allReady = selectedCount >= 2 && selectedSlots.every((s) => !s.loading && s.profile);

	const recommendation = (() => {
		if (!allReady) return null;

		const scores = slots.map(() => 0);
		const keyWins: string[][] = slots.map(() => []);

		for (const row of compareRows) {
			if (!row.weight || row.winner === null) continue;
			scores[row.winner] += row.weight;
			if (row.weight >= 2) keyWins[row.winner].push(row.label);
		}

		const contenders = selectedSlots.map((s) => s.index);
		const best = Math.max(...contenders.map((i) => scores[i]));
		if (best === 0) return null;

		const top = contenders.filter((i) => scores[i] === best);
		if (top.length > 1) {
			return { kind: 'tie' as const, names: top.map((i) => displayName(slots[i])) };
		}
		return { kind: 'winner' as const, name: displayName(slots[top[0]]), keyWins: keyWins[top[0]] };
	})();

	const heroSubtitle = (() => {
		if (selectedCount === 0) {
			return `Pick up to ${MAX_SLOTS} professors and compare rating quality, difficulty, review volume, and recent TRACE performance.`;
		}
		if (selectedCount === 1) return 'Add at least one more professor to start comparing.';
		if (selectedCount < MAX_SLOTS) {
			return `Comparing ${selectedCount} professors side-by-side. Add ${NUMBER_WORDS[MAX_SLOTS - selectedCount]} more to complete your comparison pool.`;
		}
		return `Comparing ${selectedCount} professors side-by-side.`;
	})();

	const renderProfileCard = (slot: SlotData) => {
		if (slot.loading) return <p className="compare-status">Loading profile...</p>;
		if (slot.failed && !slot.catalogProf) {
			return <p className="compare-status compare-status-error">Could not load this professor profile.</p>;
		}
		if (!slot.slug || (!slot.catalogProf && !slot.profile)) {
			return <p className="compare-status">Pick a professor for slot {slot.label}.</p>;
		}

		const { catalogProf, profile } = slot;
		const dept = catalogProf?.department ?? profile?.department ?? '';
		const imgUrl = profile?.imageUrl ?? catalogProf?.imageUrl ?? null;
		const rating = profile?.avgRating ?? catalogProf?.avgRating ?? null;
		const profSlug = catalogProf?.slug ?? slot.slug;

		const fallbackIcon = (
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
				<circle cx="12" cy="8" r="4" />
				<path d="M4 21v-1a6 6 0 0 1 6-6h4a6 6 0 0 1 6 6v1" />
			</svg>
		);

		return (
			<>
				<div className="compare-avatar-wrap">
					{imgUrl ? (
						<>
							<img
								src={imgUrl}
								alt={slot.name}
								className="compare-avatar-img"
								onError={(e) => {
									e.currentTarget.style.display = 'none';
									const fb = e.currentTarget.parentElement?.querySelector('.compare-avatar-fallback') as HTMLElement;
									if (fb) fb.style.display = 'flex';
								}}
							/>
							<div className="compare-avatar-fallback" style={{ display: 'none' }}>
								{fallbackIcon}
							</div>
						</>
					) : (
						<div className="compare-avatar-fallback">{fallbackIcon}</div>
					)}
				</div>
				<h3>{slot.name}</h3>
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

	const renderValue = (value: string) => {
		if (value === SIGN_IN_SENTINEL) {
			if (authLoading) return <span>—</span>;
			return (
				<span className="compare-lock-prompt">
					<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="compare-lock-icon" aria-hidden="true">
						<rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
						<path d="M7 11V7a5 5 0 0 1 10 0v4" />
					</svg>
					<span>
						Sign in with your <span className="husky-email">husky.neu.edu</span> account to view
					</span>
				</span>
			);
		}
		return <span>{value}</span>;
	};

	return (
		<>
			<main className="compare-page">
				<section className="compare-hero">
					<div className="compare-hero-inner">
						<p className="compare-kicker">Compare</p>
						<h1>Multi-professor comparison</h1>
						<p className="compare-subtitle">{heroSubtitle}</p>
					</div>
				</section>

				{(selectedCount > 0 || visibleCount < MAX_SLOTS) && (
					<section className="compare-chips" aria-label="Selected professors">
						{slots
							.filter((slot) => slot.slug)
							.map((slot) => {
								const imgUrl = slot.profile?.imageUrl ?? slot.catalogProf?.imageUrl ?? null;
								return (
									<div className="compare-chip" key={slot.label}>
										<Link
											className="compare-chip-main"
											to={`/professors/${slot.catalogProf?.slug ?? slot.slug}`}
											state={{ fromPage: { label: 'Compare', url: `/compare?${searchParams.toString()}` } }}
										>
											<span className={`compare-chip-avatar tone-${slot.index}`}>
												{imgUrl ? (
													<img src={imgUrl} alt="" onError={(e) => (e.currentTarget.style.display = 'none')} />
												) : (
													<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
														<circle cx="12" cy="9" r="4" />
														<path d="M4 21a8 8 0 0 1 16 0z" />
													</svg>
												)}
											</span>
											<span className="compare-chip-name">{chipName(slot)}</span>
										</Link>
										<button
											type="button"
											className="compare-chip-remove"
											aria-label={`Remove ${displayName(slot)}`}
											onClick={() => updateSlot(slot.index, '')}
										>
											×
										</button>
									</div>
								);
							})}
						{visibleCount < MAX_SLOTS && (
							<button type="button" className="compare-chip compare-chip-add" onClick={() => openSlot(visibleCount)}>
								{selectedCount === 0 ? '+ Add professor' : '+ Add'}
							</button>
						)}
					</section>
				)}

				<section
					className={`compare-controls ${hasEmptyOpenSlot ? '' : 'is-all-filled'}`}
					aria-label="Professor selection"
				>
					{slots.map((slot) => {
						const isOpen = slot.index < visibleCount;
						if (!isOpen) {
							return (
								<button
									key={slot.label}
									type="button"
									className={`compare-slot-placeholder ${slot.index === visibleCount ? 'is-next' : ''}`}
									onClick={() => openSlot(slot.index)}
								>
									Slot {slot.label} (Available)
								</button>
							);
						}

						// Extra slots (C, D) can be closed again while empty
						const canClose = !slot.slug && slot.index >= MIN_OPEN_SLOTS && slot.index === visibleCount - 1;

						return (
							<SlotSearch
								key={slot.label}
								label={`Professor ${slot.label}`}
								slug={slot.slug}
								selectedName={slot.catalogProf?.name ?? null}
								excludeSlugs={slugs.filter((s, i) => s && i !== slot.index)}
								resolveSlug={resolveSlug}
								onSelect={(slug) => updateSlot(slot.index, slug)}
								onClear={() => (canClose ? closeSlot(slot.index) : updateSlot(slot.index, ''))}
								clearLabel={slot.slug ? 'Clear' : canClose ? 'Remove' : null}
								autoFocus={focusSlot === slot.index}
							/>
						);
					})}
				</section>

				{catalogError && <p className="compare-status compare-status-error compare-status-page">{catalogError}</p>}

				<section className="compare-panels" aria-live="polite">
					{slots.map((slot) =>
						slot.index < visibleCount ? (
							<article className="compare-profile-card" key={slot.label}>
								{renderProfileCard(slot)}
							</article>
						) : (
							<button
								key={slot.label}
								type="button"
								className={`compare-add-card ${slot.index === visibleCount ? 'is-next' : ''}`}
								onClick={() => openSlot(slot.index)}
							>
								<span className="compare-add-icon" aria-hidden="true">+</span>
								<span className="compare-add-label">Add Professor</span>
							</button>
						),
					)}
				</section>

				<section className="compare-metrics">
					<div className="compare-table-card">
						<header className="compare-metrics-header">
							<h2>Key Comparison Metrics</h2>
							{anyLoading && <p>Loading comparison...</p>}
						</header>

						<div className="compare-table-scroll">
							<div
								className={`compare-table ${selectedCount > 0 ? 'has-selection' : ''}`}
								style={{ '--cols': selectedCount || MAX_SLOTS } as React.CSSProperties}
								role="table"
								aria-label="Professor metrics comparison table"
							>
								<div className="compare-row compare-row-head" role="row">
									<div className="compare-cell compare-cell-label" role="columnheader">
										Metric
									</div>
									{slots.map((slot) => (
										<div
											key={slot.label}
											className={`compare-cell compare-col-head ${slot.slug ? '' : 'is-empty is-empty-col'}`}
											role="columnheader"
										>
											<span className="compare-name-full">{slot.slug ? displayName(slot) : `Professor ${slot.label}`}</span>
											<span className="compare-name-short">{slot.slug ? firstName(slot) : `Prof. ${slot.label}`}</span>
										</div>
									))}
								</div>

								{compareRows.map((row, rowIndex) => (
									<div
										className={`compare-row ${row.label === 'Department' || row.label === 'Recent TRACE Snapshot' ? 'is-desktop-only' : ''}`}
										role="row"
										key={row.label}
										style={{ animationDelay: `${rowIndex * 0.05}s` }}
									>
										<div className="compare-cell compare-cell-label" role="rowheader">
											{row.label}
										</div>
										{row.values.map((value, i) => (
											<div
												key={SLOT_LABELS[i]}
												className={`compare-cell ${slots[i].slug ? '' : 'is-empty-col'} ${selectedCount >= 2 && row.winner === i ? 'compare-cell-winner' : ''}`}
												role="cell"
											>
												{renderValue(value)}
												{row.footnotes?.[i] && <small>{row.footnotes[i]}</small>}
											</div>
										))}
									</div>
								))}
							</div>
						</div>
					</div>
				</section>

				{recommendation && (
					<section className="compare-verdict">
						<div className="compare-verdict-inner">
							{recommendation.kind === 'tie' ? (
								<>
									<p className="compare-verdict-title">It's a tie</p>
									<p className="compare-verdict-body">
										{joinNames(recommendation.names)} are evenly matched across the key metrics.{' '}
										{recommendation.names.length === 2 ? 'Both' : 'All of them'} are solid choices, so consider
										factors like course availability or teaching style.
									</p>
								</>
							) : (
								<>
									<p className="compare-verdict-kicker">Our Recommendation</p>
									<p className="compare-verdict-title">{recommendation.name}</p>
									<p className="compare-verdict-body">
										{recommendation.keyWins.length > 0
											? `${recommendation.name} has the edge in ${joinNames(recommendation.keyWins)}, making them the stronger overall choice.`
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