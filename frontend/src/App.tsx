import { useEffect } from 'react';
import { BrowserRouter as Router, Routes, Route, Navigate, useLocation } from 'react-router-dom';
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
import Bookmarks from './pages/Bookmarks';
import NotFound from './pages/NotFound';
import Terms from './pages/Terms';
import Privacy from './pages/Privacy';
import Faq from './pages/Faq';
import Navbar from './components/Navbar';
import FeedbackTab from './components/FeedbackTab';
import AskWidget from './components/AskWidget';
import ErrorBoundary from './components/ErrorBoundary';
import './App.css';

function ScrollToTop() {
  const { pathname } = useLocation();
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [pathname]);
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
              <Route path="/account" element={<Navigate to="/bookmarks" replace />} />
              <Route path="/account/bookmarks" element={<Navigate to="/bookmarks" replace />} />
              <Route path="/terms" element={<Terms />} />
              <Route path="/privacy" element={<Privacy />} />
              <Route path="/faq" element={<Faq />} />
              <Route path="*" element={<NotFound />} />
            </Routes>
          </ErrorBoundary>
          <FeedbackTab />
          <AskWidget />
        </Router>
        <Analytics />
        <SpeedInsights />
      </BookmarksProvider>
    </AuthProvider>
  );
}

export default App;
