import { useAuth } from '../context/AuthContext';
import { useBookmarks } from '../context/BookmarksContext';
import { savePendingBookmark } from '../utils/pendingBookmark';
import './BookmarkButton.css';

interface BookmarkButtonProps {
  itemType: 'professor' | 'course';
  itemKey: string;
  size?: 'sm' | 'md';
  className?: string;
  onToggle?: () => void; // when set, parent owns the toggle (used for undo-able removal)
  /** What the sign-in prompt names when a signed-out student taps it, e.g. "Prof. Bell" or "CS 3100". */
  label?: string;
}

export default function BookmarkButton({ itemType, itemKey, size = 'sm', className, onToggle, label }: BookmarkButtonProps) {
  const { user } = useAuth();
  const { isBookmarked, toggleBookmark } = useBookmarks();
  const bookmarked = isBookmarked(itemType, itemKey);

  const handleClick = (e: React.MouseEvent) => {
    e.stopPropagation();
    e.preventDefault();
    if (!user) {
      // Saved once sign-in finishes (BookmarksContext), so the tap isn't lost to the detour.
      const name = label || `this ${itemType}`;
      savePendingBookmark({ itemType, itemKey, label: name });
      window.dispatchEvent(new CustomEvent('open-signin', { detail: { reason: `Sign in to save ${name} to your bookmarks.`, bookmark: true } }));
      return;
    }
    if (onToggle) {
      onToggle();
      return;
    }
    toggleBookmark(itemType, itemKey);
  };

  return (
    <button
      type="button"
      className={`bookmark-btn bookmark-btn-${size} ${bookmarked ? 'bookmarked' : ''} ${className ?? ''}`}
      onClick={handleClick}
      aria-pressed={bookmarked}
      aria-label={bookmarked ? 'Remove bookmark' : `Bookmark this ${itemType}`}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill={bookmarked ? 'currentColor' : 'none'}
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <path d="M19 21l-7-5-7 5V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2z" />
      </svg>
    </button>
  );
}
