import { Link } from 'react-router-dom';
import logo from '../assets/logo.jpg';
import { SocialLinkList } from './SocialLinks';
import './Footer.css';

const Footer = () => {
  return (
    <footer className="footer">
      <div className="footer-inner">
        <div className="footer-left">
          <div className="footer-brand">
            <img src={logo} alt="RateMyHusky" className="footer-brand-logo" />
            <span className="footer-brand-name"><span>Rate</span>MyHusky</span>
          </div>
          <nav className="footer-social" aria-label="RateMyHusky on Instagram and Chrome">
            <SocialLinkList />
          </nav>
        </div>
        <div className="footer-meta">
          <span className="footer-copy">
            © {new Date().getFullYear()} RateMyHusky. Made in Boston, MA.
          </span>
          <div className="footer-links">
            <Link to="/faq">FAQ</Link>
            <Link to="/terms">Terms &amp; Conditions</Link>
            <Link to="/privacy">Privacy Policy</Link>
          </div>
        </div>
      </div>
    </footer>
  );
};

export default Footer;
