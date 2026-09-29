import Footer from '../components/Footer';
import './Terms.css';

const Terms = () => {
  return (
    <div className="terms-page">
      <main className="terms-main">
        <div className="terms-shell">
          <header className="terms-header">
            <h1>Terms &amp; Conditions</h1>
            <p className="terms-meta">Effective September 23, 2026 &middot; RateMyHusky</p>
          </header>

          <div className="terms-body">
            <section className="terms-section">
              <h2>1. About the Service</h2>
              <p>
                By accessing or using RateMyHusky, you agree to be bound by these Terms and
                our{' '}
                <a href="/privacy">Privacy Policy</a>. If you do not agree, do not use the
                service.
              </p>
              <p>
                RateMyHusky is a professor and course review platform for Northeastern University
                students. It shows ratings and reviews from RateMyProfessors, excerpts of publicly
                available discussion on Reddit, and professor photos from Northeastern's public
                faculty directory pages. Alongside that data we show figures we compute from it —
                averages, department comparisons, and sentiment labels derived from Reddit text.
                Those are our estimates, not numbers published by any source.
              </p>
              <p>
                We are adding the ability for students to write reviews on RateMyHusky itself.
                Reviews submitted on RateMyHusky are owned by RateMyHusky, not by Northeastern
                University or any other third party; Section 8 sets out that ownership and the
                rules reviews must follow.
              </p>
              <p>
                RateMyHusky is an independent student project and is not affiliated with,
                endorsed by, or officially connected to Northeastern University or RateMyProfessors.
                "Husky" in "RateMyHusky" refers to the dog breed and is not intended to imply
                any association with Northeastern University's trademarks or branding.
              </p>
            </section>

            <section className="terms-section">
              <h2>2. Eligibility &amp; Access</h2>
              <p>
                Most content on RateMyHusky is publicly accessible without an account. However,
                bookmarks and writing reviews require signing in with a valid Northeastern University Google account
                (<code>@husky.neu.edu</code>).
              </p>
              <p>
                By signing in, you confirm that you are at least 18 years of age and that you
                are authorized to use the Google account you provide. Access may be revoked at
                any time if the service is misused.
              </p>
            </section>

            <section className="terms-section">
              <h2>3. Authentication &amp; Account Data</h2>
              <p>
                Sign-in is handled through Google OAuth 2.0, restricted to <code>@husky.neu.edu</code> accounts.
                When you authenticate, Google provides your name, email address, profile photo,
                and account id to RateMyHusky.
              </p>
              <p>
                This information is encoded in a JWT (JSON Web Token) that is stored in your
                browser's <code>localStorage</code>. The token expires after 30 days.
                RateMyHusky does not maintain user accounts or profiles. The only per-user data
                we store server-side is your bookmarks and any reviews you write, described below.
                Signing out deletes the token from your browser.
              </p>
              <p>
                Both are keyed to your Google account id. Bookmarks persist across sign-ins until
                you remove them or request deletion, and reviews stay up until you delete them or
                we remove them (see Section 4, "Data We Collect," and our{' '}
                <a href="/privacy">Privacy Policy</a> for what is stored, how long it is kept, and
                how to request deletion).
              </p>
            </section>

            <section className="terms-section">
              <h2>4. Data We Collect</h2>
              <p>When you use RateMyHusky, the following data may be collected or stored:</p>
              <ul>
                <li>
                  <strong>From Google sign-in:</strong> your name, email address
                  (<code>@husky.neu.edu</code>), and profile photo, stored only in your
                  browser-side JWT token.
                </li>
                <li>
                  <strong>Browser preferences and state:</strong> your theme (dark/light),
                  catalog view mode, and dismissed on-page tips are saved to{' '}
                  <code>localStorage</code>; your last review tab is held in{' '}
                  <code>sessionStorage</code> until you close the tab. This data stays on your
                  device and is never synced to our servers.
                </li>
                <li>
                  <strong>Anonymous usage data:</strong> Vercel Analytics, Vercel Speed
                  Insights, and Google Analytics collect anonymous page view and performance
                  metrics. No personally identifiable information is included.
                </li>
                <li>
                  <strong>Bookmarks:</strong> when you bookmark a professor or course while
                  signed in, we store your Google account id, the item type (professor or
                  course), the professor or course identifier, and a timestamp, server-side in
                  our database. Each account is capped at 200 bookmarks. See our{' '}
                  <a href="/privacy">Privacy Policy</a> for details on retention and deletion.
                </li>
                <li>
                  <strong>Reviews:</strong> when you write a review, we store its ratings and text,
                  the professor, course, and term it is about, when you posted it, its moderation
                  status, and your Google account id. Your account id is kept private; reviews are
                  shown anonymously (see Section 8).
                </li>
              </ul>
              <p>
                We do <strong>not</strong> log or store your search queries, which professor or
                course pages you viewed, or any other browsing activity on our servers. Your IP
                address is used in the moment to enforce rate limits and is not written to our
                database.
              </p>
            </section>

            <section className="terms-section">
              <h2>5. Feedback Form</h2>
              <p>
                RateMyHusky includes a feedback form that accepts a message type, description,
                and an email address. Submissions from this form are transmitted to
                the RateMyHusky team via email and are not stored in our database. Submitted
                information is used solely to improve the service and will not be shared with
                third parties. The email address is optional for most message types but is
                required for a "Data Deletion Request," for which (if you are signed in) your
                account identifier is also included so we can act on the correct account.
              </p>
            </section>

            <section className="terms-section">
              <h2>6. Third-Party Services</h2>
              <p>RateMyHusky integrates with the following third-party services:</p>
              <ul>
                <li>
                  <strong>Google OAuth 2.0</strong>: handles authentication. Your use of
                  Google sign-in is subject to Google's Terms of Service and Privacy Policy.
                </li>
                <li>
                  <strong>Resend</strong>: delivers feedback-form email to our team.
                </li>
                <li>
                  <strong>Cloudflare Turnstile</strong>: a CAPTCHA that protects the feedback
                  form from automated abuse.
                </li>
                <li>
                  <strong>Vercel Analytics &amp; Speed Insights</strong>: collects anonymous
                  performance and usage data to help improve the service.
                </li>
                <li>
                  <strong>Google Analytics</strong>: collects anonymous usage data such as page
                  views and engagement to help us understand how the service is used.
                  Google Analytics may use cookies; no personally identifiable information is
                  shared. Subject to{' '}
                  <a
                    href="https://policies.google.com/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Vercel, Railway &amp; Cockroach Labs</strong>: host the site, the API,
                  and the database. Availability of RateMyHusky depends on these providers.
                </li>
                <li>
                  <strong>RateMyProfessors</strong>: professor ratings and review data are
                  sourced from RateMyProfessors. This data remains subject to RateMyProfessors'
                  own terms and usage policies.
                </li>
                <li>
                  <strong>Northeastern faculty directory pages</strong>: professor photos are
                  sourced from the public college and department directory pages that publish them.
                </li>
                <li>
                  <strong>Reddit</strong>: publicly available discussion mentioning professors is
                  sourced from Reddit and remains subject to Reddit's own terms and policies.
                </li>
              </ul>
            </section>

            <section className="terms-section">
              <h2>7. Intellectual Property &amp; Data Sources</h2>
              <p>
                Review content and ratings sourced from RateMyProfessors remain subject to
                RateMyProfessors' intellectual property rights and terms of use. Faculty photos
                published on Northeastern's directory pages remain the property of Northeastern
                University, and we display them as they are published there. Reddit content
                remains the property of its authors and of Reddit. Reviews submitted on
                RateMyHusky are owned by RateMyHusky, as described in Section 8.
              </p>
              <p>
                You may not scrape, bulk-download, reproduce, or redistribute the aggregated
                data presented on RateMyHusky for any commercial or systematic purpose.
              </p>
            </section>

            <section className="terms-section">
              <h2>8. Reviews You Submit</h2>
              <p>
                This section applies to any review, rating, or comment you submit to RateMyHusky
                (a "review"). Review submission is not available yet; these terms govern every
                review once it is.
              </p>
              <p>
                <strong>Ownership.</strong> By submitting a review, you assign to RateMyHusky all
                right, title, and interest in it, including copyright, to the fullest extent
                permitted by law. Submitted reviews are owned by RateMyHusky; they are not owned by
                Northeastern University or any other third party. Where a right cannot be assigned,
                you grant RateMyHusky a perpetual, irrevocable, worldwide, royalty-free,
                sublicensable license to use, reproduce, modify, publish, display, and distribute
                the review in any form, and you waive any moral rights in it to the extent the law
                allows.
              </p>
              <p>
                <strong>What you promise.</strong> When you submit a review, you confirm that it
                describes your own honest experience as a student in that course or with that
                instructor, that you wrote it yourself, and that you have the right to give it to
                us on these terms.
              </p>
              <p><strong>Rules.</strong> A review must not:</p>
              <ul>
                <li>State as fact something you know or suspect to be false</li>
                <li>Harass, threaten, or demean anyone, or contain hate speech</li>
                <li>
                  Include anyone's contact details or other personal information, or discuss a
                  person's private life beyond their teaching
                </li>
                <li>Impersonate anyone, or review a course or instructor you have not taken</li>
                <li>Contain content you do not have the right to share, spam, or advertising</li>
              </ul>
              <p>
                <strong>Moderation.</strong> We may screen reviews before or after they are
                published, including with automated tools, and we may decline to publish or remove
                any review at our discretion. Reviews express the opinions of the students who
                write them, not the views of RateMyHusky.
              </p>
              <p>
                <strong>Anonymity.</strong> Reviews are published anonymously: your name, email
                address, and photo are never shown with a review. We keep a private record of
                which account submitted each review, and we do not disclose it unless the law
                requires us to.
              </p>
              <p>
                <strong>Deleting your review.</strong> You can delete a review you wrote at any
                time, which removes it from the site and from our database. Otherwise a review
                stays up until you delete it or we remove it.
              </p>
            </section>

            <section className="terms-section">
              <h2>9. Acceptable Use</h2>
              <p>By using RateMyHusky, you agree not to:</p>
              <ul>
                <li>Use automated scripts, bots, or crawlers to access the service (rate limiting is enforced)</li>
                <li>Attempt to access, steal, or forge other users' session tokens or credentials</li>
                <li>
                  Circumvent rate limits, access controls, the CAPTCHA on the feedback form, or a
                  maintenance page
                </li>
                <li>
                  Use data from this platform — including review text and Reddit excerpts — to
                  harass, target, defame, or harm any individual professor or instructor
                </li>
                <li>Attempt to reverse-engineer, overload, or otherwise disrupt the service</li>
              </ul>
              <p>
                We enforce per-IP rate limits across the site. Repeated misuse may result in
                suspension of your access, as described in Section 16.
              </p>
            </section>

            <section className="terms-section">
              <h2>10. Availability &amp; Changes to the Service</h2>
              <p>
                RateMyHusky is a student-run project offered without any uptime commitment. We
                take the site down for maintenance, add and remove features, and switch features
                off when they need work. Source data is refreshed on a schedule, so figures shown
                on a page can change between visits, and a professor or course can appear, change,
                or disappear as the sources and our matching improve.
              </p>
            </section>

            <section className="terms-section">
              <h2>11. Professor &amp; Instructor Removal Requests</h2>
              <p>
                If you are a professor or instructor and you want your information removed from
                RateMyHusky, email{' '}
                <a href="mailto:legal@ratemyhusky.com">legal@ratemyhusky.com</a> or use the
                feedback form. We honor these requests: your page, ratings, comments, and Reddit
                mentions are deleted, and your name is added to a removal list that every data
                loader checks, so a later refresh does not bring them back. We cannot remove your
                data from RateMyProfessors or Reddit themselves — contact those sources
                directly. Our <a href="/privacy">Privacy Policy</a> describes what we publish and
                the limits of what removal covers.
              </p>
            </section>

            <section className="terms-section">
              <h2>12. No Warranties &amp; Data Accuracy</h2>
              <p>
                Professor ratings and review comments come from external sources and from the
                students who write them, and may be incomplete, outdated, or inaccurate. Figures we
                compute — averages, per-term trends, and Reddit sentiment labels — depend
                on that source data and on matching a professor's name across systems that spell
                it differently, so they can be wrong even when the sources are right. RateMyHusky
                makes no guarantees about the accuracy, completeness, or timeliness of anything
                displayed on the platform.
              </p>
              <p>
                We encourage you to use RateMyHusky as one of several resources when making
                course registration decisions, not as the sole basis for those decisions. If you
                spot something wrong, report it through the feedback form under "Incorrect Data."
              </p>
            </section>

            <section className="terms-section">
              <h2>13. Limitation of Liability</h2>
              <p>
                RateMyHusky is provided "as-is" without warranties of any kind, express or
                implied. To the fullest extent permitted by law, RateMyHusky and its developers
                are not liable for any damages arising from your use of or inability to use
                the service, including decisions made based on data presented on this platform.
              </p>
            </section>

            <section className="terms-section">
              <h2>14. Changes to These Terms</h2>
              <p>
                We may update these Terms from time to time. The effective date at the top of
                this page will be updated when changes are made. Continued use of RateMyHusky
                after changes are posted constitutes your acceptance of the revised Terms.
              </p>
            </section>

            <section className="terms-section">
              <h2>15. Indemnification</h2>
              <p>
                You agree to defend, indemnify, and hold harmless RateMyHusky and its developers
                from and against any claims, damages, losses, or expenses (including reasonable
                legal fees) arising out of or related to your use of the service, your violation
                of these Terms, or your violation of any third-party rights.
              </p>
            </section>

            <section className="terms-section">
              <h2>16. Termination</h2>
              <p>
                We reserve the right to suspend or terminate your access to RateMyHusky at any
                time, with or without notice, if we believe you have violated these Terms or are
                misusing the service. Upon termination, your right to use the service ceases
                immediately.
              </p>
            </section>

            <section className="terms-section">
              <h2>17. DMCA &amp; Content Removal</h2>
              <p>
                RateMyHusky shows publicly available data from third-party sources and reviews
                written by students. If you
                believe content displayed on this platform infringes your copyright or should be
                removed for another legal reason, please contact us at{' '}
                <a href="mailto:legal@ratemyhusky.com">legal@ratemyhusky.com</a> with a
                description of the content and the basis for your removal request. We will
                review and respond in good faith. Professors and instructors asking to be removed
                should see Section 11, which does not require a legal basis.
              </p>
            </section>

            <section className="terms-section">
              <h2>18. Governing Law</h2>
              <p>
                These Terms are governed by the laws of the Commonwealth of Massachusetts,
                without regard to conflict of law principles. Any disputes arising from these
                Terms or your use of RateMyHusky shall be resolved exclusively in the state or
                federal courts located in Suffolk County, Massachusetts, and you consent to
                personal jurisdiction in those courts.
              </p>
            </section>

            <section className="terms-section">
              <h2>19. Severability</h2>
              <p>
                If any provision of these Terms is found to be unenforceable or invalid under
                applicable law, that provision will be modified to the minimum extent necessary
                to make it enforceable, or severed if modification is not possible. The remaining
                provisions will continue in full force and effect.
              </p>
            </section>

            <section className="terms-section terms-section--last">
              <h2>20. Contact</h2>
              <p>
                If you have questions about these Terms or want to report an issue, please email
                us at <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a>.
              </p>
            </section>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default Terms;
