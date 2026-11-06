// Margin-based scoring for /compare: each professor gets a 0-100 score from the weighted metrics
// they have data for, and a lead under TIE_POINTS is a tie.
export const TIE_POINTS = 2;

export type MetricId = 'rating' | 'difficulty' | 'takeAgain';

interface MetricConfig {
	weight: number;
	better: 'higher' | 'lower';
	scale: (value: number) => number; // 0..1, longer bar is better
}

export const METRICS: Record<MetricId, MetricConfig> = {
	rating: { weight: 3, better: 'higher', scale: (v) => v / 5 },
	// Inverted so a longer bar always means better: 1 (easiest) is full, 5 is empty
	difficulty: { weight: 1.5, better: 'lower', scale: (v) => (5 - v) / 4 },
	takeAgain: { weight: 2, better: 'higher', scale: (v) => v / 100 },
};

export interface ScoreMetric extends MetricConfig {
	id: MetricId;
	values: (number | null)[]; // by slot index
}

export interface DroppedMetric {
	id: MetricId;
	missing: number[]; // slot indexes with no value
}

export type ScoreResult =
	| { kind: 'tie'; tied: number[]; scores: Record<number, number>; dropped: DroppedMetric[] }
	| {
			kind: 'winner';
			winner: number;
			runnerUp: number;
			scores: Record<number, number>;
			ahead: MetricId[];
			behind: MetricId[];
			dropped: DroppedMetric[];
	  };

const COPY: Record<MetricId, { ahead: string; behind: string; dropped: string }> = {
	rating: { ahead: 'overall rating', behind: 'higher overall rating', dropped: 'Overall rating' },
	difficulty: { ahead: 'difficulty', behind: 'lower difficulty', dropped: 'Difficulty' },
	takeAgain: { ahead: 'would-take-again rate', behind: 'higher would-take-again rate', dropped: 'Would take again' },
};

export const joinNames = (names: string[]) => {
	if (names.length <= 2) return names.join(' and ');
	return `${names.slice(0, -1).join(', ')}, and ${names[names.length - 1]}`;
};

// "overall rating (weight 3), would-take-again rate (2), and difficulty (1.5)"
export function weightsText(): string {
	const ids = (Object.keys(METRICS) as MetricId[]).sort((a, b) => METRICS[b].weight - METRICS[a].weight);
	return joinNames(ids.map((id, i) => `${COPY[id].ahead} (${i === 0 ? 'weight ' : ''}${METRICS[id].weight})`));
}

export function scoreProfessors(contenders: number[], metrics: ScoreMetric[]): ScoreResult | null {
	const dropped: DroppedMetric[] = [];
	for (const metric of metrics) {
		const missing = contenders.filter((slot) => metric.values[slot] == null);
		if (missing.length > 0) dropped.push({ id: metric.id, missing });
	}

	// Each professor is scored only on the metrics they have, so adding a professor can't change anyone else's score
	const scores: Record<number, number> = {};
	for (const slot of contenders) {
		const counted = metrics.filter((metric) => metric.values[slot] != null);
		const totalWeight = counted.reduce((sum, metric) => sum + metric.weight, 0);
		if (totalWeight === 0) continue;
		const weighted = counted.reduce((sum, metric) => sum + metric.weight * metric.scale(metric.values[slot] as number), 0);
		scores[slot] = (100 * weighted) / totalWeight;
	}
	const scored = contenders.filter((slot) => slot in scores);
	if (scored.length < 2) return null;

	const ranked = [...scored].sort((a, b) => scores[b] - scores[a]);
	const [top, second] = ranked;
	if (scores[top] - scores[second] < TIE_POINTS) {
		return { kind: 'tie', tied: ranked.filter((slot) => scores[top] - scores[slot] < TIE_POINTS), scores, dropped };
	}

	const ahead: MetricId[] = [];
	const behind: MetricId[] = [];
	for (const metric of metrics) {
		const w = metric.values[top];
		const r = metric.values[second];
		if (w == null || r == null || w === r) continue;
		if ((w > r) === (metric.better === 'higher')) ahead.push(metric.id);
		else behind.push(metric.id);
	}
	return { kind: 'winner', winner: top, runnerUp: second, scores, ahead, behind, dropped };
}

export function winnerSentence(r: Extract<ScoreResult, { kind: 'winner' }>, lastName: (slot: number) => string): string {
	const w = lastName(r.winner);
	const ru = lastName(r.runnerUp);
	const lead = `${w} scores ${Math.round(r.scores[r.winner])} to ${ru}'s ${Math.round(r.scores[r.runnerUp])}. Ahead on ${joinNames(r.ahead.map((id) => COPY[id].ahead))}`;
	if (r.behind.length === 0) return `${lead}.`;
	return `${lead}, which outweighs ${ru}'s ${joinNames(r.behind.map((id) => COPY[id].behind))}.`;
}

export function droppedSentence(d: DroppedMetric, name: (slot: number) => string): string {
	const names = d.missing.map(name);
	return `${COPY[d.id].dropped} isn't counted for ${joinNames(names)}, who ${names.length === 1 ? 'has' : 'have'} no data for it.`;
}
