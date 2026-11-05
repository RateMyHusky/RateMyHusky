import { useEffect, useRef } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation, useNavigationType } from 'react-router-dom';
import { Analytics } from '@vercel/analytics/react';
import { SpeedInsights } from '@vercel/speed-insights/react';
import { AuthProvider } from './context/AuthContext';
import { BookmarksProvider } from './context/BookmarksContext';
import Homepage from './pages/Homepage';
import Professor from './pages/Professor';
import ProfessorCatalog from './pages/ProfessorCatalog';
import Courses from './pages/Courses';
import Course from './pages/Course';
import Departments from './pages/Departments';
import Department from './pages/Department';
import Compare from './pages/Compare';
import Rate from './pages/Rate';
import Bookmarks from './pages/Bookmarks';
import NotFound from './pages/NotFound';
import Terms from './pages/Terms';
import Privacy from './pages/Privacy';
import Faq from './pages/Faq';
import Navbar from './components/Navbar';
import FeedbackTab from './components/FeedbackTab';
import ThemeToggle from './components/ThemeToggle';
import ErrorBoundary from './components/ErrorBoundary';
import { RATE_ENABLED } from './config';
import './App.css';

function ScrollToTop() {
  const { pathname } = useLocation();
  const navType = useNavigationType();
  const lastPath = useRef<string | null>(null);
  useEffect(() => {
    if (lastPath.current === pathname) return;
    lastPath.current = pathname;
    const path = pathname.replace(/\/$/, '');
    // Back onto a catalog: useCatalogScroll restores the saved position instead
    if (navType === 'POP' && (path === '/professors' || path === '/courses')) return;
    window.scrollTo(0, 0);
  }, [pathname, navType]);
  return null;
}


function App() {
  return (
    <AuthProvider>
      <BookmarksProvider>
        <Router>
          <ScrollToTop />
          <Navbar />
          <ErrorBoundary>
            <Routes>
              <Route path="/" element={<Homepage />} />
              <Route path="/professors" element={<ProfessorCatalog />} />
              <Route path="/professors/:slug" element={<Professor />} />
              <Route path="/courses" element={<Courses />} />
              <Route path="/courses/:code" element={<Course />} />
              <Route path="/departments" element={<Departments />} />
              <Route path="/departments/:slug" element={<Department />} />
              <Route path="/compare" element={<Compare />} />
              <Route path="/bookmarks" element={<Bookmarks />} />
              {RATE_ENABLED && <Route path="/rate" element={<Rate />} />}
              <Route path="/account" element={<Navigate to="/bookmarks" replace />} />
              <Route path="/account/bookmarks" element={<Navigate to="/bookmarks" replace />} />
              <Route path="/terms" element={<Terms />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/faq" element={<Faq />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </ErrorBoundary>
          <FeedbackTab />
          <ThemeToggle />
        </Router>
        <Analytics />
        <SpeedInsights />
      </BookmarksProvider>
    </AuthProvider>
  );
}

export default App;
