import './StatTile.css';

/** Renders as a button only when given an onClick — a plain tile stays a div
 *  rather than an inert button nobody can use. */
export default function StatTile({
  value,
  label,
  onClick,
}: {
  value: string;
  label: string;
  onClick?: () => void;
}) {
  const inner = (
    <>
      <b>{value}</b>
      <span>{label}</span>
    </>
  );

  if (!onClick) return <div className="stat-tile">{inner}</div>;

  return (
    <button className="stat-tile tappable" type="button" onClick={onClick}>
      {inner}
    </button>
  );
}
