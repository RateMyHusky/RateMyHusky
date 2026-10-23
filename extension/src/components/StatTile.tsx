import './StatTile.css';

export default function StatTile({ value, label }: { value: string; label: string }) {
  return (
    <div className="stat-tile">
      <b>{value}</b>
      <span>{label}</span>
    </div>
  );
}
