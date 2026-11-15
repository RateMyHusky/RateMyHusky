import { Component } from 'react';
import type { ReactNode } from 'react';
import { useLocation } from 'react-router-dom';
import LoadError from './LoadError';
import '../pages/Course.css';

interface ErrorBoundaryState {
  hasError: boolean;
}

// Minimal top-level crash guard: a malformed Ask payload (or any other render-time throw)
// used to unmount the entire React tree (white screen). This catches it and shows the shared
// LoadError screen inside a .course-page wrapper (navbar offset, themed background), and clears
// itself when the route changes so the Navbar can still get the user out. No logging service.
class Boundary extends Component<{ children: ReactNode; pathname: string }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  componentDidUpdate(prev: { pathname: string }) {
    if (this.state.hasError && prev.pathname !== this.props.pathname) {
      this.setState({ hasError: false });
    }
  }

  render() {
    if (this.state.hasError) {
      return <div className="course-page"><LoadError /></div>;
    }
    return this.props.children;
  }
}

const ErrorBoundary = ({ children }: { children: ReactNode }) => {
  const { pathname } = useLocation();
  return <Boundary pathname={pathname}>{children}</Boundary>;
};

export default ErrorBoundary;
