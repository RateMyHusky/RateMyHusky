import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import neuIcon from '../assets/neu-circle-icon.png';
import './SignInModal.css';

const CLOSE_DURATION = 200; // ms — must match CSS animation duration

interface Props {
  open: boolean;
  onClose: () => void;
}

export default function SignInModal({ open, onClose }: Props) {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const [closing, setClosing] = useState(false);

  const animatedClose = (callback?: () => void) => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
      callback?.();
    }, CLOSE_DURATION);
  };

  // Auto-close modal when user logs in (e.g. after mobile redirect)
  useEffect(() => {
    if (user && open) {
      onClose();
    }
  }, [user, open, onClose]);

  useEffect(() => {
    if (open) {
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }
    return () => { document.body.style.overflow = ''; };
  }, [open]);

  if (!open) return null;

  const handleLinkClick = (e: React.MouseEvent<HTMLAnchorElement>, path: string) => {
    e.preventDefault();
    animatedClose(() => navigate(path));
  };

  return (
    <div className={`signin-modal-overlay${closing ? ' closing' : ''}`} onClick={() => animatedClose()}>
      <div className={`signin-modal${closing ? ' closing' : ''}`} onClick={e => e.stopPropagation()}>
        <button className="signin-modal-close" onClick={() => animatedClose()} aria-label="Close">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
            <line x1="18" y1="6" x2="6" y2="18" />
            <line x1="6" y1="6" x2="18" y2="18" />
          </svg>
        </button>

        <h2 className="signin-modal-title">Sign In</h2>

        <p className="signin-modal-desc">
          Sign in to use our AI <strong>Ask</strong> feature, read student reviews, bookmark professors and courses, and other sign-in only features. We currently only support valid <strong>husky.neu.edu</strong> accounts.
        </p>

        <img src={neuIcon} alt="Northeastern University" className="signin-modal-logo" />

        <p className="signin-modal-terms">
          By signing in, you agree to our{' '}
          <a href="/terms" onClick={e => handleLinkClick(e, '/terms')}>Terms of Service</a>
          {' '}and{' '}
          <a href="/privacy" onClick={e => handleLinkClick(e, '/privacy')}>Privacy Policy</a>.
        </p>

        <button className="signin-modal-google-btn" onClick={login}>
          <svg className="google-icon" viewBox="0 0 24 24">
            <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92a5.06 5.06 0 0 1-2.2 3.32v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.1z" fill="#4285F4"/>
            <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
            <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18A10.96 10.96 0 0 0 1 12c0 1.77.42 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
            <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
          </svg>
          Sign in with Google
        </button>
      </div>
    </div>
  );
}
