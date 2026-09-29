import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import {
	LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend,
} from 'recharts';
import type { CourseSection } from '../api/api';
import Dropdown from './Dropdown';
import { termSortKey } from '../utils/termUtils';
import './SectionHistoryChart.css';

type Mode = 'aggregate' | 'individual';

interface Props {
	sections: CourseSection[];
}

interface TermPoint {
	term: string;
	termId: number;
	year: number;
	avg: number | null;
	trace: number | null;
	rmp: number | null;
}

function buildChartData(sections: CourseSection[]): TermPoint[] {
	const termMap = new Map<number, { title: string; year: number; traceSum: number; traceCount: number; rmpSum: number; rmpCount: number }>();

	for (const s of sections) {
		let entry = termMap.get(s.termId);
		if (!entry) {
			// Extract year from 6-digit term code before stripping it (e.g. "202101" → 2021)
			const codeYear = s.termTitle.match(/\b(20\d{2})\d{2}\b/)?.[1];
			const cleaned = s.termTitle.replace(/^\d{6}:\s*/, '').replace(/\s*\d{6}/g, '').trim();
			const yearMatch = cleaned.match(/\b(20\d{2})\b/);
			const year = yearMatch ? Number(yearMatch[1]) : (codeYear ? Number(codeYear) : 0);
			// If stripping the code left the title without a year, reattach it
			const title = yearMatch ? cleaned : (codeYear ? `${cleaned} ${codeYear}` : cleaned);
			entry = { title, year, traceSum: 0, traceCount: 0, rmpSum: 0, rmpCount: 0 };
			termMap.set(s.termId, entry);
		}
		if (s.overallRating != null) {
			entry.traceSum += s.overallRating;
			entry.traceCount += 1;
		}
		if (s.rmpRating != null) {
			entry.rmpSum += s.rmpRating;
			entry.rmpCount += 1;
		}
	}

	return Array.from(termMap.entries())
		.sort(([, a], [, b]) => termSortKey(a.title) - termSortKey(b.title))
		.map(([termId, d]) => {
			const trace = d.traceCount > 0 ? +(d.traceSum / d.traceCount).toFixed(2) : null;
			const rmp = d.rmpCount > 0 ? +(d.rmpSum / d.rmpCount).toFixed(2) : null;
			let avg: number | null = null;
			if (trace != null && rmp != null) avg = +((trace + rmp) / 2).toFixed(2);
			else if (trace != null) avg = trace;
			else if (rmp != null) avg = rmp;
			return { term: d.title, termId, year: d.year, avg, trace, rmp };
		})
		.filter(p => p.avg !== null || p.trace !== null || p.rmp !== null);
}

const SEASON_ABBR: Record<string, string> = {
	spring: 'Sp', fall: 'Fa', summer: 'Su', winter: 'Wi',
};

function abbreviateTerm(term: string): string {
	const m = term.match(/(Spring|Fall|Summer|Winter)\s*(?:[A-Z0-9])?\s*(20\d{2})/i);
	if (!m) return term;
	const abbr = SEASON_ABBR[m[1].toLowerCase()] ?? m[1].slice(0, 2);
	return `${abbr} '${m[2].slice(2)}`;
}

function yearOnly(term: string): string {
	return term.match(/\b(20\d{2})\b/)?.[1] ?? term;
}

function useWindowWidth() {
	const [width, setWidth] = useState(() => window.innerWidth);
	useEffect(() => {
		const onResize = () => setWidth(window.innerWidth);
		window.addEventListener('resize', onResize);
		return () => window.removeEventListener('resize', onResize);
	}, []);
	return width;
}

const RANGE_OPTIONS = [
	{ label: 'All Years', value: 0 },
	{ label: '1 Year', value: 1 },
	{ label: '5 Years', value: 5 },
	{ label: '10 Years', value: 10 },
] as const;

// ── Professor multi-select filter ─────────────────────────────────────────────

function ProfessorFilter({
	professors,
	selected,
	onChange,
}: {
	professors: string[];
	selected: Set<string>;
	onChange: (next: Set<string>) => void;
}) {
	const [open, setOpen] = useState(false);
	const [search, setSearch] = useState('');
	const ref = useRef<HTMLDivElement>(null);

	const filtered = professors.filter(p => p.toLowerCase().includes(search.toLowerCase()));

	useEffect(() => {
		if (!open) return;
		const handler = (e: MouseEvent) => {
			if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
		};
		document.addEventListener('mousedown', handler);
		return () => document.removeEventListener('mousedown', handler);
	}, [open]);

	const toggle = (p: string) => {
		const next = new Set(selected);
		if (next.has(p)) next.delete(p);
		else next.add(p);
		onChange(next);
	};

	const allSelected = selected.size === professors.length;
	const label = allSelected
		? 'All professors'
		: selected.size === 0
			? 'No professors'
			: selected.size === 1
				? [...selected][0]
				: `${selected.size} professors`;

	return (
		<div className="sh-prof-filter" ref={ref}>
			<button
				type="button"
				className={`sh-prof-toggle ${open ? 'open' : ''}`}
				onClick={() => setOpen(!open)}
				aria-expanded={open}
			>
				<span className="sh-prof-toggle-label">{label}</span>
				<span className="sh-prof-toggle-icon">
					<span className="sh-prof-bar" />
					<span className="sh-prof-bar" />
					<span className="sh-prof-bar" />
				</span>
			</button>

			{open && (
				<div className="sh-prof-dropdown">
					{professors.length > 5 && (
						<input
							className="sh-prof-search"
							type="text"
							placeholder="Search professors…"
							value={search}
							onChange={e => setSearch(e.target.value)}
							autoFocus
						/>
					)}
					<div className="sh-prof-actions">
						<button type="button" className="sh-prof-action-link" onClick={() => onChange(new Set(professors))}>Select all</button>
						<button type="button" className="sh-prof-action-link" onClick={() => onChange(new Set())}>Clear all</button>
					</div>
					<div className="sh-prof-list">
						{filtered.map(p => (
							<label key={p} className="sh-prof-option">
								<input
									type="checkbox"
									checked={selected.has(p)}
									onChange={() => toggle(p)}
								/>
								<span>{p}</span>
							</label>
						))}
						{filtered.length === 0 && (
							<p className="sh-prof-empty">No professors found</p>
						)}
					</div>
				</div>
			)}

		</div>
	);
}

// ─────────────────────────────────────────────────────────────────────────────

export default function SectionHistoryChart({ sections }: Props) {
	const [mode, setMode] = useState<Mode>('aggregate');
	const [range, setRange] = useState(0);
	const tabsRef = useRef<HTMLDivElement>(null);
	const [pillStyle, setPillStyle] = useState({ left: 0, width: 0, opacity: 0 });
	const [pillReady, setPillReady] = useState(false);
	const windowWidth = useWindowWidth();

	// ── Professor filter ──────────────────────────────────────────────────────
	const allProfessors = useMemo(() => {
		const names = new Set<string>();
		sections.forEach(s => { if (s.instructor) names.add(s.instructor); });
		return Array.from(names).sort();
	}, [sections]);

	const [selectedProfessors, setSelectedProfessors] = useState<Set<string>>(new Set());
	const hasInitializedProfs = useRef(false);
	useEffect(() => {
		if (allProfessors.length > 0 && !hasInitializedProfs.current) {
			setSelectedProfessors(new Set(allProfessors));
			hasInitializedProfs.current = true;
		}
	}, [allProfessors]);

	const filteredSections = useMemo(() => {
		if (selectedProfessors.size === allProfessors.length) return sections;
		return sections.filter(s => selectedProfessors.has(s.instructor));
	}, [sections, selectedProfessors, allProfessors.length]);

	// ─────────────────────────────────────────────────────────────────────────

	const updatePill = useCallback(() => {
		if (!tabsRef.current) return;
		const activeTab = tabsRef.current.querySelector('.sh-toggle-btn.active') as HTMLElement;
		if (activeTab) {
			setPillStyle({ left: activeTab.offsetLeft, width: activeTab.offsetWidth, opacity: 1 });
		}
	}, []);

	useLayoutEffect(() => {
		updatePill();
	}, [mode, updatePill]);

	useEffect(() => {
		updatePill();
		const timer = setTimeout(() => setPillReady(true), 150);
		return () => clearTimeout(timer);
	}, [updatePill]);

	// Check if there's any raw data at all (before professor filtering)
	const hasAnyData = useMemo(() => buildChartData(sections).length > 0, [sections]);

	const allData = useMemo<TermPoint[]>(() => buildChartData(filteredSections), [filteredSections]);

	const data = useMemo(() => {
		if (range === 0) return allData;
		const maxYear = Math.max(...allData.map(p => p.year).filter(y => y > 0));
		return allData.filter(p => p.year >= maxYear - range + 1);
	}, [allData, range]);

	// Responsive X-axis config
	const xAxis = useMemo(() => {
		if (windowWidth < 768) {
			// Mobile: year only, no rotation, show ~4 labels max
			const interval = Math.max(0, Math.ceil(data.length / 4) - 1);
			return {
				tickFormatter: yearOnly,
				angle: 0,
				textAnchor: 'middle' as const,
				height: 28,
				interval,
			};
		}
		if (windowWidth < 1024) {
			// Tablet: abbreviated "Sp '25", slight angle
			return {
				tickFormatter: abbreviateTerm,
				angle: -20,
				textAnchor: 'end' as const,
				height: 44,
				interval: 'preserveStartEnd' as const,
			};
		}
		// Desktop: full label, current behavior
		return {
			tickFormatter: undefined,
			angle: -20,
			textAnchor: 'end' as const,
			height: 60,
			interval: 'preserveStartEnd' as const,
		};
	}, [windowWidth, data.length]);

	if (!hasAnyData) return null;

	return (
		<div className="sh-chart-wrap">
			<div className="sh-chart-controls">
				<div className="sh-toggle" ref={tabsRef}>
					<div
						className={`sh-pill-bg ${pillReady ? 'animate' : ''}`}
						style={{
							transform: `translateX(${pillStyle.left}px)`,
							width: `${pillStyle.width}px`,
							opacity: pillStyle.opacity,
							visibility: pillStyle.opacity === 0 ? 'hidden' : 'visible',
						}}
					/>
					<button
						type="button"
						className={`sh-toggle-btn ${mode === 'aggregate' ? 'active' : ''}`}
						onClick={() => setMode('aggregate')}
					>
						Aggregate
					</button>
					<button
						type="button"
						className={`sh-toggle-btn ${mode === 'individual' ? 'active' : ''}`}
						onClick={() => setMode('individual')}
					>
						Individual
					</button>
				</div>

				{allProfessors.length > 1 && (
					<ProfessorFilter
						professors={allProfessors}
						selected={selectedProfessors}
						onChange={setSelectedProfessors}
					/>
				)}

				<Dropdown
					className="sh-range-dropdown"
					options={RANGE_OPTIONS.map(o => ({ value: String(o.value), label: o.label }))}
					value={String(range)}
					onChange={(v) => setRange(Number(v))}
				/>
			</div>

			<div className="sh-chart-container">
				{data.length === 0 ? (
					<div className="sh-no-data">No data for the selected professors and range.</div>
				) : (
					<ResponsiveContainer width="100%" height={300}>
						<LineChart key={`${range}-${mode}`} data={data} margin={{ top: 12, right: 20, left: 30, bottom: 4 }}>
							<CartesianGrid strokeDasharray="3 3" stroke="var(--sh-grid)" />
							<XAxis
								dataKey="term"
								tick={{ fontSize: 11, fill: 'var(--sh-axis)' }}
								angle={xAxis.angle}
								textAnchor={xAxis.textAnchor}
								height={xAxis.height}
								interval={xAxis.interval}
								tickFormatter={xAxis.tickFormatter}
							/>
							<YAxis
								domain={[1, 5]}
								ticks={[1, 2, 3, 4, 5]}
								tick={{ fontSize: 11, fill: 'var(--sh-axis)' }}
								width={32}
							/>
							<Tooltip
								contentStyle={{
									background: 'var(--sh-tooltip-bg)',
									border: '1px solid var(--sh-tooltip-border)',
									borderRadius: 8,
									fontSize: 13,
									color: 'var(--sh-tooltip-text)',
								}}
								formatter={(value) => typeof value === 'number' ? value.toFixed(2) : String(value ?? '')}
							/>
							<Legend />
							{mode === 'aggregate' ? (
								<Line
									type="monotone"
									dataKey="avg"
									name="Avg Rating"
									stroke="#5ec4a8"
									strokeWidth={2.5}
									dot={{ r: 3, fill: '#5ec4a8' }}
									activeDot={{ r: 5 }}
									connectNulls
								/>
							) : (
								<>
									<Line
										type="monotone"
										dataKey="trace"
										name="Student Reviews"
										stroke="#5ec4a8"
										strokeWidth={2.5}
										dot={{ r: 3, fill: '#5ec4a8' }}
										activeDot={{ r: 5 }}
										connectNulls
									/>
									<Line
										type="monotone"
										dataKey="rmp"
										name="RMP"
										stroke="#e8736c"
										strokeWidth={2.5}
										dot={{ r: 3, fill: '#e8736c' }}
										activeDot={{ r: 5 }}
										connectNulls
									/>
								</>
							)}
						</LineChart>
					</ResponsiveContainer>
				)}
			</div>
		</div>
	);
}
