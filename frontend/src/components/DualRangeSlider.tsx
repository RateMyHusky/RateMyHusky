import { useState } from 'react';

export default function DualRangeSlider({
  min,
  max,
  step,
  valueLow,
  valueHigh,
  onChangeLow,
  onChangeHigh,
  labelLow,
  labelHigh,
}: {
  min: number;
  max: number;
  step: number;
  valueLow: number;
  valueHigh: number;
  onChangeLow: (v: number) => void;
  onChangeHigh: (v: number) => void;
  labelLow: string;
  labelHigh: string;
}) {
  const [lastActive, setLastActive] = useState<'low' | 'high'>('low');
  const range = max - min;
  const lowPct = ((valueLow - min) / range) * 100;
  const highPct = ((valueHigh - min) / range) * 100;

  return (
    <div className="dual-range">
      <div className="dual-range-track">
        <div
          className="dual-range-fill"
          style={{ left: `${lowPct}%`, width: `${highPct - lowPct}%` }}
        />
      </div>
      <input
        type="range"
        className="dual-range-input"
        aria-label={labelLow}
        style={{ zIndex: lastActive === 'low' ? 4 : 3 }}
        min={min}
        max={max}
        step={step}
        value={valueLow}
        onPointerDown={() => setLastActive('low')}
        onChange={e => {
          const v = parseFloat(e.target.value);
          onChangeLow(Math.min(v, valueHigh));
        }}
      />
      <input
        type="range"
        className="dual-range-input"
        aria-label={labelHigh}
        style={{ zIndex: lastActive === 'high' ? 4 : 3 }}
        min={min}
        max={max}
        step={step}
        value={valueHigh}
        onPointerDown={() => setLastActive('high')}
        onChange={e => {
          const v = parseFloat(e.target.value);
          onChangeHigh(Math.max(v, valueLow));
        }}
      />
    </div>
  );
}
