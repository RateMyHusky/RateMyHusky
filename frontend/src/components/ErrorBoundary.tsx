import { Component } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import LoadError from './LoadError';
import '../pages/Course.css';

interface ErrorBoundaryState {
  hasError: boolean;
}

interface ErrorBoundaryProps {
  children: ReactNode;
  // Replaces the page-sized LoadError screen, e.g. null for a corner widget that should just go away.
  fallback?: ReactNode;
  // Runs once when a crash is caught, e.g. to drop saved state that would crash again.
  onError?: () => void;
}

// Minimal top-level crash guard: a malformed Ask payload (or any other render-time throw)
// used to unmount the entire React tree (white screen). This catches it and shows the shared
// LoadError screen inside a .course-page wrapper (navbar offset, themed background), and clears
// itself when the route changes so the Navbar can still get the user out. No logging service.
class Boundary extends Component<ErrorBoundaryProps & { pathname: string }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidCatch() {
    this.props.onError?.();
  }

  componentDidUpdate(prev: { pathname: string }) {
    if (this.state.hasError && prev.pathname !== this.props.pathname) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;
      return <div className="course-page"><LoadError /></div>;
    }
    return this.props.children;
  }
}

const ErrorBoundary = ({ children, fallback, onError }: ErrorBoundaryProps) => {
  const { pathname } = useLocation();
  return <Boundary pathname={pathname} fallback={fallback} onError={onError}>{children}</Boundary>;
};

export default ErrorBoundary;
