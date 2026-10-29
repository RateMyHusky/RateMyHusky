import { createContext, useContext, useState, useEffect, useCallback } from 'react';
import type { ReactNode } from 'react';
import { useAuth } from './AuthContext';
import { fetchBookmarks, addBookmark, removeBookmark } from '../api/api';
import type { CatalogProfessor, CatalogCourse } from '../api/api';
import { takePendingBookmark } from '../utils/pendingBookmark';
import './BookmarksContext.css';

const SAVED_TOAST_MS = 4000;

type ItemType = 'professor' | 'course';

export type BookmarkedProfessor = CatalogProfessor & { bookmarkedAt: string };
export type BookmarkedCourse = CatalogCourse & { bookmarkedAt: string };

interface BookmarksContextType {
  loading: boolean;
  isBookmarked: (type: ItemType, key: string) => boolean;
  toggleBookmark: (type: ItemType, key: string) => Promise<void>;
  bookmarkedProfessors: BookmarkedProfessor[];
  bookmarkedCourses: BookmarkedCourse[];
}

const BookmarksContext = createContext<BookmarksContextType>({
  loading: false,
  isBookmarked: () => false,
  toggleBookmark: async () => {},
  bookmarkedProfessors: [],
  bookmarkedCourses: [],
});

export function BookmarksProvider({ children }: { children: ReactNode }) {
  const { user } = useAuth();
  const [loading, setLoading] = useState(true);
  const [professorSlugs, setProfessorSlugs] = useState<Set<string>>(new Set());
  const [courseCodes, setCourseCodes] = useState<Set<string>>(new Set());
  const [bookmarkedProfessors, setBookmarkedProfessors] = useState<BookmarkedProfessor[]>([]);
  const [bookmarkedCourses, setBookmarkedCourses] = useState<BookmarkedCourse[]>([]);
  // "Saved <label> to your bookmarks", after a bookmark tapped signed-out is saved on sign-in.
  const [savedToast, setSavedToast] = useState<string | null>(null);

  useEffect(() => {
    if (!savedToast) return;
    const t = setTimeout(() => setSavedToast(null), SAVED_TOAST_MS);
    return () => clearTimeout(t);
  }, [savedToast]);

  // Single fetch whenever the user transitions from signed-out to signed-in;
  // clears everything on logout. This is what lets every card on a catalog
  // page check bookmark status via an O(1) Set lookup instead of N requests.
  useEffect(() => {
    if (!user) {
      setProfessorSlugs(new Set());
      setCourseCodes(new Set());
      setBookmarkedProfessors([]);
      setBookmarkedCourses([]);
      setLoading(false);
      return;
    }
    setLoading(true);
    // Set when this account's session ends (sign-out or a switch): the fetch, add, fetch chain
    // below can outlast it, and must not repopulate the next state with this account's list.
    let cancelled = false;
    const apply = (data: { professors: BookmarkedProfessor[]; courses: BookmarkedCourse[] }) => {
      setProfessorSlugs(new Set(data.professors.map(p => p.slug)));
      setCourseCodes(new Set(data.courses.map(c => c.code)));
      setBookmarkedProfessors(data.professors);
      setBookmarkedCourses(data.courses);
    };
    // Taken on sign-in only: a signed-in tap never stores one.
    const pending = takePendingBookmark();
    fetchBookmarks()
      .then(async data => {
        const saved = pending && (pending.itemType === 'professor'
          ? data.professors.some(p => p.slug === pending.itemKey)
          : data.courses.some(c => c.code === pending.itemKey));
        if (pending && !saved) {
          try {
            await addBookmark(pending.itemType, pending.itemKey);
            data = await fetchBookmarks();
            if (cancelled) return;
            setSavedToast(`Saved ${pending.label} to your bookmarks`);
          } catch {
            // Not saved: the flag stays empty and the student can tap it again.
          }
        }
        if (!cancelled) apply(data);
      })
      .catch(() => {
        // Signed in but couldn't load bookmarks — leave state empty rather than stale.
      })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.email]);

  const isBookmarked = useCallback(
    (type: ItemType, key: string) => (type === 'professor' ? professorSlugs.has(key) : courseCodes.has(key)),
    [professorSlugs, courseCodes]
  );

  const toggleBookmark = useCallback(async (type: ItemType, key: string) => {
    const currentlyBookmarked = type === 'professor' ? professorSlugs.has(key) : courseCodes.has(key);
    const removedProfessor = type === 'professor' && currentlyBookmarked
      ? bookmarkedProfessors.find(p => p.slug === key)
      : undefined;
    const removedCourse = type === 'course' && currentlyBookmarked
      ? bookmarkedCourses.find(c => c.code === key)
      : undefined;

    const flip = (prev: Set<string>) => {
      const next = new Set(prev);
      if (currentlyBookmarked) next.delete(key); else next.add(key);
      return next;
    };
    if (type === 'professor') {
      setProfessorSlugs(flip);
      if (currentlyBookmarked) setBookmarkedProfessors(prev => prev.filter(p => p.slug !== key));
    } else {
      setCourseCodes(flip);
      if (currentlyBookmarked) setBookmarkedCourses(prev => prev.filter(c => c.code !== key));
    }

    try {
      if (currentlyBookmarked) {
        await removeBookmark(type, key);
      } else {
        await addBookmark(type, key);
        // Fetch the full list so the newly-added item's display data (name,
        // rating, etc.) is available — we only have its key client-side.
        const data = await fetchBookmarks();
        setBookmarkedProfessors(data.professors);
        setBookmarkedCourses(data.courses);
      }
    } catch {
      const unflip = (prev: Set<string>) => {
        const next = new Set(prev);
        if (currentlyBookmarked) next.add(key); else next.delete(key);
        return next;
      };
      if (type === 'professor') {
        setProfessorSlugs(unflip);
        if (removedProfessor) setBookmarkedProfessors(prev => [removedProfessor, ...prev]);
      } else {
        setCourseCodes(unflip);
        if (removedCourse) setBookmarkedCourses(prev => [removedCourse, ...prev]);
      }
    }
  }, [professorSlugs, courseCodes, bookmarkedProfessors, bookmarkedCourses]);

  return (
    <BookmarksContext.Provider
      value={{ loading, isBookmarked, toggleBookmark, bookmarkedProfessors, bookmarkedCourses }}
    >
      {children}
      {savedToast && <div className="saved-toast" role="status">{savedToast}</div>}
    </BookmarksContext.Provider>
  );
}

export const useBookmarks = () => useContext(BookmarksContext);
