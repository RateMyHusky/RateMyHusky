import { GearIcon, BackIcon } from './icons';
import './Header.css';

export default function Header({
  onBack,
  onSettings,
}: {
  onBack?: () => void;
  onSettings?: () => void;
}) {
  return (
    <header className="bar">
      {onBack && (
        <button className="icon-btn back" type="button" onClick={onBack} aria-label="Back">
          <BackIcon />
        </button>
      )}
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
