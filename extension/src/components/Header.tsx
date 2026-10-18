import { GearIcon } from './icons';
import './Header.css';

export default function Header({ onSettings }: { onSettings?: () => void }) {
  return (
    <header className="bar">
      <img className="mark" src="neu-husky-icon.png" alt="" width={22} height={22} />
      <span className="wordmark">
        <span>Rate</span>MyHusky
      </span>
      <button
        className="icon-btn"
        type="button"
        onClick={onSettings}
        disabled={!onSettings}
        aria-label="Settings"
        title="Settings"
      >
        <GearIcon />
      </button>
    </header>
  );
}
