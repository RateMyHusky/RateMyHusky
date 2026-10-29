import { useEffect, useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { fetchDepartmentDetail, type DepartmentDetail, type DepartmentProfessor } from '../api/api';
import Footer from '../components/Footer';
import Breadcrumbs from '../components/Breadcrumbs';
import Seo from '../components/Seo';
import NotFound from './NotFound';
import './Course.css';
import './Department.css';

type SortKey = 'name' | 'avgRating' | 'difficulty' | 'wouldTakeAgainPct' | 'totalRatings';
type SortDir = 'asc' | 'desc';

function compareNullable(a: number | null, b: number | null, dir: SortDir): number {
  // Rows with no data sort last regardless of direction.
  if (a == null && b == null) return 0;
  if (a == null) return 1;
  if (b == null) return -1;
  return dir === 'asc' ? a - b : b - a;
}

export default function Department() {
  const { slug = '' } = useParams<{ slug: string }>();
  const [department, setDepartment] = useState<DepartmentDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [notFound, setNotFound] = useState(false);
  const [sortKey, setSortKey] = useState<SortKey>('avgRating');
  const [sortDir, setSortDir] = useState<SortDir>('desc');

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setNotFound(false);
    fetchDepartmentDetail(slug).then(data => {
      if (cancelled) return;
      if (!data) {
        setDepartment(null);
        setNotFound(true);
      } else {
        setDepartment(data);
      }
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [slug]);

  // Match the prerender (render.py department_html): professors without a slug are
  // excluded from the table, summary sentences, and JSON-LD alike.
  const linkedProfessors = useMemo(
    () => (department ? department.professors.filter(
      (p): p is DepartmentProfessor & { slug: string } => !!p.slug,
    ) : []),
    [department],
  );

  const sortedProfessors = useMemo(() => {
    const rows = [...linkedProfessors];
    rows.sort((a, b) => {
      if (sortKey === 'name') {
        return sortDir === 'asc' ? a.name.localeCompare(b.name) : b.name.localeCompare(a.name);
      }
      return compareNullable(a[sortKey], b[sortKey], sortDir);
    });
    return rows;
  }, [linkedProfessors, sortKey, sortDir]);

  const toggleSort = (key: SortKey) => {
    if (key === sortKey) {
      setSortDir(d => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir(key === 'name' ? 'asc' : 'desc');
    }
  };

  if (loading) {
    return (
      <div className="course-page">
        <div className="course-shell">
          <div className="course-loading">Loading department data...</div>
        </div>
      </div>
    );
  }

  if (notFound || !department) {
    return <NotFound />;
  }

  const { name, professorCount, avgRating } = department;
  const top = linkedProfessors.length ? [...linkedProfessors].sort((a, b) => (b.avgRating ?? -1) - (a.avgRating ?? -1))[0] : null;

  const summarySentences = [
    avgRating != null
      ? `The ${name} department at Northeastern University has ${professorCount} rated professors averaging ${avgRating}/5.`
      : `The ${name} department at Northeastern University has ${professorCount} rated professors.`,
  ];
  if (top) {
    summarySentences.push(
      `The highest-rated is ${top.name} (${top.avgRating}/5 from ${top.totalRatings} ratings).`
    );
  }
  const wtaValues = linkedProfessors
    .map(p => p.wouldTakeAgainPct)
    .filter((v): v is number => v != null);
  if (wtaValues.length) {
    const avgWta = Math.round((wtaValues.reduce((sum, v) => sum + v, 0) / wtaValues.length) * 10) / 10;
    summarySentences.push(`On average, ${avgWta}% of students would take these professors again.`);
  }
  const summary = summarySentences.join(' ');

  const canonical = `https://ratemyhusky.com/departments/${slug}`;
  const itemListJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'ItemList',
    itemListElement: linkedProfessors.map((p, i) => ({
      '@type': 'ListItem',
      position: i + 1,
      name: p.name,
      url: `https://ratemyhusky.com/professors/${p.slug}`,
    })),
  };
  const breadcrumbJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'BreadcrumbList',
    itemListElement: [
      { '@type': 'ListItem', position: 1, name: 'Home', item: 'https://ratemyhusky.com/' },
      { '@type': 'ListItem', position: 2, name: 'Departments', item: 'https://ratemyhusky.com/departments' },
      { '@type': 'ListItem', position: 3, name, item: canonical },
    ],
  };

  const sortArrow = (key: SortKey) => (sortKey === key ? (sortDir === 'asc' ? ' ↑' : ' ↓') : '');

  return (
    <div className="course-page">
      <Seo
        title={`${name} Professors at Northeastern — Ratings & Reviews`}
        description={summary}
        canonical={canonical}
        jsonLd={[itemListJsonLd, breadcrumbJsonLd]}
      />
      <div className="course-shell">
        <Breadcrumbs items={[
          { label: 'Departments', to: '/departments' },
          { label: name },
        ]} />

        <header className="course-hero">
          <div>
            <h1>Northeastern {name} — Professor Ratings & Reviews</h1>
            <p className="course-dept">{summary}</p>
          </div>
        </header>

        <section className="course-panel">
          <div className="course-panel-header">
            <h2>All Professors</h2>
          </div>
          <div className="dept-table-wrap">
            <table className="course-table dept-hub-table">
              <thead>
                <tr>
                  <th><button type="button" className="dept-sort-btn" onClick={() => toggleSort('name')}>Name{sortArrow('name')}</button></th>
                  <th><button type="button" className="dept-sort-btn" onClick={() => toggleSort('avgRating')}>Rating{sortArrow('avgRating')}</button></th>
                  <th><button type="button" className="dept-sort-btn" onClick={() => toggleSort('difficulty')}>Difficulty{sortArrow('difficulty')}</button></th>
                  <th><button type="button" className="dept-sort-btn" onClick={() => toggleSort('wouldTakeAgainPct')}>Would take again{sortArrow('wouldTakeAgainPct')}</button></th>
                  <th><button type="button" className="dept-sort-btn" onClick={() => toggleSort('totalRatings')}>Ratings{sortArrow('totalRatings')}</button></th>
                </tr>
              </thead>
              <tbody>
                {sortedProfessors.map(p => (
                  <tr key={p.slug}>
                    <td><Link to={`/professors/${p.slug}`}>{p.name}</Link></td>
                    <td>{p.avgRating != null ? p.avgRating.toFixed(2) : '—'}</td>
                    <td>{p.difficulty != null ? p.difficulty.toFixed(2) : '—'}</td>
                    <td>{p.wouldTakeAgainPct != null ? `${Math.round(p.wouldTakeAgainPct)}%` : '—'}</td>
                    <td>{p.totalRatings.toLocaleString()}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>
      <Footer />
    </div>
  );
}
