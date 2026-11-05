import { Component } from 'react';
import type { ReactNode } from 'react';

interface ErrorBoundaryState {
  hasError: boolean;
}

// Minimal top-level crash guard: a malformed Ask payload (or any other render-time throw)
// used to unmount the entire React tree (white screen). This catches it and shows a plain
// reload prompt instead. No logging service — just prevents the blank page.
// `fallback` replaces the page-sized prompt, e.g. null for a corner widget that should just go away.
class ErrorBoundary extends Component<{ children: ReactNode; fallback?: ReactNode }, ErrorBoundaryState> {
  state: ErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): ErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback !== undefined) return this.props.fallback;
      return <p style={{ textAlign: 'center', padding: '3rem 1rem' }}>Something went wrong — reload the page.</p>;
    }
    return this.props.children;
  }
}

export default ErrorBoundary;
