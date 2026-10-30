import { Link, useLocation } from 'react-router-dom';
import { loadAskSession } from '../utils/askSession';
import './Breadcrumbs.css';

interface BreadcrumbItem {
  label: string;
  to?: string;
}

interface BreadcrumbsProps {
  items: BreadcrumbItem[];
}

const Breadcrumbs = ({ items }: BreadcrumbsProps) => {
  const location = useLocation();

  // If we came from a specific page (e.g. Compare), prepend that as the first breadcrumb
  const fromPage = location.state?.fromPage as { label: string; url: string } | undefined;
  const goatedCollege = location.state?.goatedCollege as string | undefined;
  // Set on citation clicks from the Ask box: the "← Ask" crumb must re-hydrate the homepage
  // Ask box (a plain homepage nav clears it instead), so carry the flag on that first link.
  const restoreAsk = location.state?.restoreAsk as boolean | undefined;
  // Back/forward can replay this state after clearAskSession() already wiped storage (e.g.
  // logo-click then Back). Only show the "← Ask" crumb when a session actually still exists;
  // otherwise fall back to the normal breadcrumb items.
  const showAskCrumb = fromPage && (!restoreAsk || loadAskSession() !== null);
  // A catalog crumb returns to the filtered list the visitor came from: fromCatalog is
  // that list's full URL (/professors?… or /courses?…), set by the catalog's cards.
  const fromCatalog = location.state?.fromCatalog as string | undefined;
  const catalogHref = (to?: string) => (to && fromCatalog?.split('?')[0] === to ? fromCatalog : to);

  const resolvedItems = showAskCrumb
    ? [{ label: fromPage.label, to: fromPage.url }, ...items.filter(item => item.to !== '/professors' && item.to !== '/courses')]
    : items;

  return (
    <nav className="breadcrumbs" aria-label="Breadcrumb">
      <ol className="breadcrumbs-list">
        {resolvedItems.map((item, i) => {
          const isLast = i === resolvedItems.length - 1;
          const href = catalogHref(item.to);
          // The "← Ask" crumb (the prepended fromPage link, i===0) carries restoreAsk so the
          // homepage rebuilds the Ask answer; other crumbs only carry goatedCollege.
          const linkState = showAskCrumb && i === 0 && restoreAsk
            ? { restoreAsk: true }
            : goatedCollege ? { goatedCollege } : undefined;

          return (
            <li key={i} className="breadcrumbs-item">
              {!isLast && href ? (
                <>
                  <Link to={href} state={linkState} className="breadcrumbs-link">{item.label}</Link>
                  <span className="breadcrumbs-separator" aria-hidden="true">
                    <svg width="7" height="11" viewBox="0 0 7 11" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M1 1l4.5 4.5L1 10" />
                    </svg>
                  </span>
                </>
              ) : (
                <span className="breadcrumbs-current" aria-current="page">{item.label}</span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
};

export default Breadcrumbs;
