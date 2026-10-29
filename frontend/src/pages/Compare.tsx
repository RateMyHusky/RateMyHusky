import { Fragment, useEffect, useRef, useState } from 'react';
import type React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { fetchProfessorFull, fetchSearchSuggestions } from '../api/api';
import type { ProfessorPage, ProfessorSuggestion } from '../api/api';
import StarRating from '../components/StarRating';
import Footer from '../components/Footer';
import { photoThumb, thumbOnError } from '../utils/photoThumb';

import './Compare.css';

/* ---- Slot config ----
   Each slot maps to a URL param: /compare?a=slug&b=slug&c=slug&d=slug */
const SLOT_KEYS = ['a', 'b', 'c', 'd'] as const;
const SLOT_LABELS = ['A', 'B', 'C', 'D'] as const;
const MAX_SLOTS = SLOT_KEYS.length;
const MIN_OPEN_SLOTS = 2; // A and B always show a search box

const MIN_RATINGS = 10; // below this a professor is flagged and can't be marked best

interface ProfileEntry {
	status: 'loading' | 'ready' | 'error';
	profile: ProfessorPage | null;
}

interface SlotData {
	index: number;
	label: string;
	slug: string;
	profile: ProfessorPage | null;
	loading: boolean;
	failed: boolean;
	name: string;
}

interface MetricRow {
	label: string;
	hint: string; // which way is better, shown under the label
	verdictLabel: string;
	values: (number | null)[];
	format: (value: number) => string;
	scale: (value: number) => number; // 0..1 on a fixed scale for the bar; longer is better
	winners: number[]; // slot indexes sharing the best value; empty for no best
	runnersUp: number[]; // slot indexes sharing the second-best value; empty for none
	ranked: number; // how many slots were ranked (eligible and with a value)
	weight: number;
	showCount?: boolean;
}

/* ---- Helpers ---- */
const parseMaybeNumber = (value: number | null | undefined) => {
	if (typeof value !== 'number' || Number.isNaN(value)) return null;
	return value;
};

const formatMetric = (value: number | null | undefined, digits = 2) => {
	const parsed = parseMaybeNumber(value);
	return parsed === null ? '—' : parsed.toFixed(digits);
};

/* Ranks the eligible slots (enough ratings) that have a value, best value first.
   Tied slots share a place. Best needs at least two distinct values, so nobody stands
   out when everyone ties. Second best needs a third, lower value: with two values it
   would just be the worst, so it is left empty. Like Olympic medals, a tie for best
   uses up second place too ("1, 1, 3"), so there is no second best after it. */
const pickRanks = (
	values: (number | null | undefined)[],
	eligible: boolean[],
	mode: 'higher' | 'lower' = 'higher',
	decimals = 2,
): { winners: number[]; runnersUp: number[]; ranked: number } => {
	const factor = 10 ** decimals;
	const valid = values
		.map((value, index) => {
			const parsed = parseMaybeNumber(value);
			if (parsed === null || !eligible[index]) return null;
			// Round to displayed precision so ties match what the user sees
			return { index, value: Math.round(parsed * factor) / factor };
		})
		.filter((entry): entry is { index: number; value: number } => entry !== null);

	const distinct = Array.from(new Set(valid.map((entry) => entry.value))).sort((a, b) =>
		mode === 'higher' ? b - a : a - b,
	);
	const slotsAt = (value: number) => valid.filter((entry) => entry.value === value).map((entry) => entry.index);

	const winners = distinct.length >= 2 ? slotsAt(distinct[0]) : [];
	return {
		winners,
		runnersUp: distinct.length >= 3 && winners.length === 1 ? slotsAt(distinct[1]) : [],
		ranked: valid.length,
	};
};

const clamp01 = (value: number) => Math.min(1, Math.max(0, value));

// "jane-doe-2" -> "Jane Doe": a stand-in name for a shared-link slot before (or without) its profile
const nameFromSlug = (slug: string) =>
	slug
		.replace(/-\d+$/, '')
		.split('-')
		.filter(Boolean)
		.map((part) => part[0].toUpperCase() + part.slice(1))
		.join(' ');

const joinNames = (names: string[]) => {
	if (names.length <= 2) return names.join(' and ');
	return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`;
};

/* ---- One search box (replaces the duplicated left/right search code) ---- */
interface SlotSearchProps {
	label: string;
	slug: string;
	selectedName: string | null;
	excludeSlugs: string[];
	onSelect: (prof: ProfessorSuggestion) => void;
	onClear: () => void;
	clearLabel: string | null;
	autoFocus: boolean;
}

function SlotSearch({
	label,
	slug,
	selectedName,
	excludeSlugs,
	onSelect,
	onClear,
	clearLabel,
	autoFocus,
}: SlotSearchProps) {
	const [query, setQuery] = useState('');
	const [suggestions, setSuggestions] = useState<ProfessorSuggestion[]>([]);
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
				// A result without a slug can't be loaded, so it is dropped rather than guessed at
				const professorResults = results
					.filter((result): result is ProfessorSuggestion => result.type === 'professor')
					.filter((prof) => prof.slug && !excluded.has(prof.slug))
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
	}, [query, slug, selectedName, excludeKey]);

	useEffect(() => {
		const handleOutsideClick = (event: MouseEvent) => {
			if (wrapperRef.current && !wrapperRef.current.contains(event.target as Node)) {
				setOpen(false);
			}
		};
		document.addEventListener('mousedown', handleOutsideClick);
		return () => document.removeEventListener('mousedown', handleOutsideClick);
	}, []);

	const select = (prof: ProfessorSuggestion) => {
		setQuery(prof.name);
		setOpen(false);
		setActiveIndex(-1);
		onSelect(prof);
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
					{suggestions.map((prof, index) => (
						<button
							key={prof.slug}
							className={`compare-suggestion ${slug === prof.slug || activeIndex === index ? 'active' : ''}`}
							onClick={() => select(prof)}
							type="button"
						>
							<span className="compare-suggestion-main">{prof.name}</span>
							<span className="compare-suggestion-meta">
								{prof.dept ? `${prof.dept} • ` : ''}{prof.rating !== null ? prof.rating.toFixed(2) : '—'}
							</span>
						</button>
					))}
				</div>
			)}
		</div>
	);
}

/* ---- Page ---- */
function Compare() {
	const [searchParams, setSearchParams] = useSearchParams();

	const [entries, setEntries] = useState<Record<string, ProfileEntry>>({});
	// Names picked from search, so a slot has a name before its profile arrives
	const [pickedNames, setPickedNames] = useState<Record<string, string>>({});
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

	// Load a profile for every selected slug
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
			const res = await fetchProfessorFull(slug);
			if (cancelled) return;
			setEntries((prev) => ({
				...prev,
				[slug]: res.ok ? { status: 'ready', profile: res.data } : { status: 'error', profile: null },
			}));
		});

		return () => {
			cancelled = true;
		};
	}, [slugKey]);

	// Refetch one profile after it failed. A result for a slug that was removed meanwhile is dropped.
	const retryProfile = async (slug: string) => {
		setEntries((prev) => ({ ...prev, [slug]: { status: 'loading', profile: null } }));
		const res = await fetchProfessorFull(slug);
		setEntries((prev) =>
			prev[slug] ? { ...prev, [slug]: res.ok ? { status: 'ready', profile: res.data } : { status: 'error', profile: null } } : prev
		);
	};

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
		const entry = slug ? entries[slug] : undefined;
		const profile = entry?.profile ?? null;
		return {
			index,
			label: SLOT_LABELS[index],
			slug,
			profile,
			loading: Boolean(slug) && (!entry || entry.status === 'loading'),
			failed: entry?.status === 'error',
			// Picked name first, so the name (and the search box synced to it) stays put when the profile arrives.
			// A slot from a shared link has no picked name, so it shows one built from the slug until then.
			name: pickedNames[slug] ?? profile?.identity.name ?? (slug ? nameFromSlug(slug) : ''),
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

	/* Professor data shape (api.ts v2): summary = blended numbers across sources.
	   RMP is the only live source, so the Overall Rating row is the RMP rating. */
	const rating = slots.map((s) => (isReady(s) ? s.profile?.summary.rating ?? null : null));
	const difficulty = slots.map((s) => (isReady(s) ? s.profile?.summary.difficulty ?? null : null));
	const takeAgain = slots.map((s) => (isReady(s) ? s.profile?.summary.wouldTakeAgainPct ?? null : null));
	const numRatings = slots.map((s) => (isReady(s) ? s.profile?.summary.numRatings ?? null : null));
	// Too few ratings to trust: still shown, but flagged and never marked best
	const lowSample = numRatings.map((n) => n !== null && n < MIN_RATINGS);
	const eligible = slots.map((s, i) => isReady(s) && !lowSample[i]);

	const departments = slots.map((s) => {
		if (!isReady(s)) return '—';
		const identity = s.profile?.identity;
		if (!identity) return '—';
		if (!identity.department) return identity.college || '—';
		return identity.college ? `${identity.department} (${identity.college})` : identity.department;
	});

	const outOfFive = (v: number) => v / 5;
	const metricRows: MetricRow[] = [
		{
			label: 'Overall Rating',
			hint: 'out of 5',
			verdictLabel: 'overall rating',
			values: rating,
			format: (v) => v.toFixed(2),
			scale: outOfFive,
			...pickRanks(rating, eligible),
			weight: 3,
			showCount: true,
		},
		{
			label: 'Difficulty',
			hint: 'lower is easier',
			verdictLabel: 'difficulty',
			values: difficulty,
			format: (v) => v.toFixed(2),
			// Inverted so a longer bar always means better: 1 (easiest) is full, 5 is empty
			scale: (v) => (5 - v) / 4,
			...pickRanks(difficulty, eligible, 'lower'),
			weight: 1.5,
		},
		{
			label: 'Would Take Again',
			hint: 'of raters',
			verdictLabel: 'would-take-again rate',
			values: takeAgain,
			format: (v) => `${v.toFixed(0)}%`,
			scale: (v) => v / 100,
			...pickRanks(takeAgain, eligible, 'higher', 0),
			weight: 2,
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

		// Rows only rank professors with enough ratings; with fewer than two, say why there's no pick
		const rankable = selectedSlots.filter((s) => eligible[s.index]);
		if (rankable.length < 2) {
			const flagged = selectedSlots.filter((s) => lowSample[s.index]);
			if (flagged.length === 0) return null;
			return { kind: 'lowSample' as const, names: flagged.map(displayName) };
		}

		const scores = slots.map(() => 0);
		const keyWins: string[][] = slots.map(() => []);

		// Only an outright lead scores; a shared best is shown in the table but splits nothing here
		for (const row of metricRows) {
			if (row.winners.length !== 1) continue;
			const [winner] = row.winners;
			scores[winner] += row.weight;
			if (row.weight >= 2) keyWins[winner].push(row.verdictLabel);
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
			return `Pick up to ${MAX_SLOTS} professors and compare ratings, difficulty, and how many students would take them again.`;
		}
		if (selectedCount === 1) return 'Add at least one more professor to start comparing.';
		return `Comparing ${selectedCount} professors side-by-side.`;
	})();

	const renderProfileCard = (slot: SlotData) => {
		if (slot.loading) return <p className="compare-status">Loading profile...</p>;
		if (slot.failed) {
			return (
				<div className="compare-status">
					<p className="compare-status-error">Could not load {displayName(slot)}'s profile.</p>
					<button type="button" className="compare-retry" onClick={() => retryProfile(slot.slug)}>
						Try again
					</button>
				</div>
			);
		}
		if (!slot.slug || !slot.profile) {
			return <p className="compare-status">Pick a professor for slot {slot.label}.</p>;
		}

		const { identity, summary } = slot.profile;
		const dept = identity.department;
		const imgUrl = identity.imageUrl;
		const rating = summary.rating;
		const profSlug = identity.slug;

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
						// Keyed so a slot switching professors gets a fresh <img>, not the last one's error state
						<Fragment key={imgUrl}>
							<img
								src={photoThumb(imgUrl)}
								alt={slot.name}
								className="compare-avatar-img"
								onError={thumbOnError(imgUrl, (img) => {
									img.style.display = 'none';
									const fb = img.parentElement?.querySelector('.compare-avatar-fallback') as HTMLElement;
									if (fb) fb.style.display = 'flex';
								})}
							/>
							<div className="compare-avatar-fallback" style={{ display: 'none' }}>
								{fallbackIcon}
							</div>
						</Fragment>
					) : (
						<div className="compare-avatar-fallback">{fallbackIcon}</div>
					)}
				</div>
				<h3>
					<span className={`compare-col-dot tone-${slot.index}`} aria-hidden="true" />
					{slot.name}
				</h3>
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

	const anyLowSample = lowSample.some(Boolean);

	const renderMetricCell = (row: MetricRow, i: number) => {
		const value = row.values[i];
		// Wait for every profile, so Best and 2nd don't move as late ones arrive
		const isBest = allReady && row.winners.includes(i);
		const isSecond = allReady && row.runnersUp.includes(i);
		const count = numRatings[i];
		const rankClass = isBest ? 'compare-cell-winner' : isSecond ? 'compare-cell-second' : '';
		// Too few ratings to rank: mute the value on every row and say why
		const unranked = lowSample[i] && value !== null;
		const lowSampleTitle = `Fewer than ${MIN_RATINGS} ratings, so this professor isn't marked best`;
		const bestTied = row.winners.length > 1;
		const secondTied = row.runnersUp.length > 1;

		return (
			<div
				key={SLOT_LABELS[i]}
				className={`compare-cell ${slots[i].slug ? '' : 'is-empty-col'} ${rankClass} ${unranked ? 'is-low-sample' : ''}`}
				role="cell"
			>
				<span className="compare-value">
					{value === null ? '—' : row.format(value)}
					{isBest && (
						<span className="compare-best">
							<span aria-hidden="true">✓</span>
							<span className="compare-rank-long" aria-hidden="true">{bestTied ? ' Tied best' : ' Best'}</span>
							{bestTied && (
								<span className="compare-rank-short" aria-hidden="true">
									{' '}
									Tie
								</span>
							)}
							<span className="visually-hidden">{bestTied ? ', tied for best' : `, best among ${row.ranked}`}</span>
						</span>
					)}
					{isSecond && (
						<span className="compare-second">
							<span className="compare-rank-long" aria-hidden="true">{secondTied ? 'Tied 2nd' : '2nd'}</span>
							<span className="compare-rank-short" aria-hidden="true">{secondTied ? 'T-2nd' : '2nd'}</span>
							<span className="visually-hidden">{secondTied ? ', tied for second best' : ', second best'}</span>
						</span>
					)}
				</span>
				{value !== null && (
					<span className="compare-bar" aria-hidden="true">
						<i style={{ width: `${clamp01(row.scale(value)) * 100}%` }} />
					</span>
				)}
				{row.showCount && count !== null && (
					<small
						className={lowSample[i] ? 'compare-low-sample' : undefined}
						title={lowSample[i] ? lowSampleTitle : undefined}
					>
						{count.toLocaleString()} {count === 1 ? 'rating' : 'ratings'}
					</small>
				)}
				{!row.showCount && unranked && (
					<small className="compare-low-sample" title={lowSampleTitle}>
						Few ratings
					</small>
				)}
			</div>
		);
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
								const imgUrl = slot.profile?.identity.imageUrl ?? null;
								return (
									<div className="compare-chip" key={slot.label}>
										<Link
											className="compare-chip-main"
											to={`/professors/${slot.profile?.identity.slug ?? slot.slug}`}
											state={{ fromPage: { label: 'Compare', url: `/compare?${searchParams.toString()}` } }}
										>
											<span className={`compare-chip-avatar tone-${slot.index}`}>
												{imgUrl ? (
													<img key={imgUrl} src={photoThumb(imgUrl)} alt="" onError={thumbOnError(imgUrl, (img) => (img.style.display = 'none'))} />
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
								selectedName={slot.name || null}
								excludeSlugs={slugs.filter((s, i) => s && i !== slot.index)}
								onSelect={(prof) => {
									setPickedNames((prev) => ({ ...prev, [prof.slug]: prof.name }));
									updateSlot(slot.index, prof.slug);
								}}
								onClear={() => (canClose ? closeSlot(slot.index) : updateSlot(slot.index, ''))}
								clearLabel={slot.slug ? 'Clear' : canClose ? 'Remove' : null}
								autoFocus={focusSlot === slot.index}
							/>
						);
					})}
				</section>

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
											<span className="compare-col-name">
												{slot.slug && <span className={`compare-col-dot tone-${slot.index}`} aria-hidden="true" />}
												<span className="compare-name-full">{slot.slug ? displayName(slot) : `Professor ${slot.label}`}</span>
												<span className="compare-name-short">{slot.slug ? firstName(slot) : `Prof. ${slot.label}`}</span>
											</span>
										</div>
									))}
								</div>

								<div className="compare-row is-desktop-only" role="row">
									<div className="compare-cell compare-cell-label" role="rowheader">
										Department
									</div>
									{departments.map((value, i) => (
										<div key={SLOT_LABELS[i]} className={`compare-cell ${slots[i].slug ? '' : 'is-empty-col'}`} role="cell">
											<span>{value}</span>
										</div>
									))}
								</div>

								{metricRows.map((row, rowIndex) => (
									<div
										className="compare-row"
										role="row"
										key={row.label}
										style={{ animationDelay: `${(rowIndex + 1) * 0.05}s` }}
									>
										<div className="compare-cell compare-cell-label" role="rowheader">
											{row.label}
											<span className="compare-row-hint">{row.hint}</span>
										</div>
										{slots.map((_, i) => renderMetricCell(row, i))}
									</div>
								))}
							</div>
						</div>

						{anyLowSample && (
							<p className="compare-table-note">
								Professors with fewer than {MIN_RATINGS} ratings are shown in grey and aren't ranked.
							</p>
						)}
					</div>
				</section>

				{recommendation && (
					<section className="compare-verdict">
						<div className="compare-verdict-inner">
							{recommendation.kind === 'lowSample' ? (
								<>
									<p className="compare-verdict-title">Not enough ratings to recommend</p>
									<p className="compare-verdict-body">
										{joinNames(recommendation.names)} {recommendation.names.length === 1 ? 'has' : 'have'} fewer
										than {MIN_RATINGS} ratings, so there aren't two professors with enough ratings to compare
										fairly.
									</p>
								</>
							) : recommendation.kind === 'tie' ? (
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