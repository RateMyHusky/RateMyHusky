import Footer from '../components/Footer';
import { BANNER_SINCE, RATE_ENABLED } from '../config';
import './Terms.css';

const Privacy = () => {
  return (
    <div className="terms-page">
      <main className="terms-main">
        <div className="terms-shell">
          <header className="terms-header">
            <h1>Privacy Policy</h1>
            <p className="terms-meta">Effective October 28, 2026 &middot; RateMyHusky</p>
          </header>

          <div className="terms-body">
            <section className="terms-section">
              <h2>1. Introduction</h2>
              <p>
                RateMyHusky is an aggregator of professor and course information for
                Northeastern University students.
                {RATE_ENABLED ? ' It also collects first-party ratings from students.' : ''} This Privacy Policy describes what information
                we collect, how we use it, and the choices you have. By using RateMyHusky,
                you also agree to our{' '}
                <a href="/terms">Terms &amp; Conditions</a>.
              </p>
              <p>
                RateMyHusky is an independent student project and is not affiliated with,
                endorsed by, or officially connected to Northeastern University or RateMyProfessors.
              </p>
              <p>
                If you are a professor or instructor whose information appears on the site,
                see <em>Information About Professors &amp; Instructors</em> (Section 8) — that
                section covers what we publish about you and how to ask us to remove it.
              </p>
            </section>

            <section className="terms-section">
              <h2>2. Information We Collect</h2>
              <p>We collect only the minimum information needed to operate the service:</p>
              <ul>
                <li>
                  <strong>Google Sign-In:</strong> when you authenticate with your{' '}
                  <code>@husky.neu.edu</code> Google account, we receive your name, email
                  address, profile photo, and Google account id. Your name, email, and photo
                  are encoded in a JWT token stored in your browser and are never written to a
                  server-side database. Your Google account id is stored server-side if you
                  bookmark a professor or course — see the Bookmarks item below.
                </li>
                <li>
                  <strong>Browser preferences:</strong> your selected theme (dark/light), your
                  catalog view mode, and flags recording that you dismissed an on-page tip are
                  saved to <code>localStorage</code> on your device only and are never
                  transmitted to our servers.
                  {RATE_ENABLED ? ' The one exception is the rating device ID, described under Ratings below.' : ''} Which review tab you had open on a professor page
                  is held in <code>sessionStorage</code> so navigation works, and is dropped
                  when you close the tab.
                </li>
                <li>
                  <strong>IP address:</strong> your IP address is used in the moment a request
                  arrives to apply rate limits, and it is discarded when the request finishes.
                  We never store your raw IP address.
                  {RATE_ENABLED && (<>
                  {' '}If you submit a rating, we store keyed
                  hashes of your IP address and its network, plus the type of network. The hashes
                  are kept for 30 days and then deleted in routine cleanup. See the Ratings
                  item below.
                  </>)}
                </li>
                <li>
                  <strong>Feedback form:</strong> the feedback form collects a message type,
                  description, and an optional email address. Submissions are transmitted to
                  the RateMyHusky team via email and are not stored in a database. Submitted
                  information is used solely to improve the service. The form is protected by
                  a CAPTCHA challenge (see Third-Party Services). If you submit an
                  "Account Deletion" request, you must be signed in and an email address is
                  required so we can respond; your account identifier is included so we can
                  locate the data held for your account and delete it. That account identifier is
                  derived from your sign-in token at the time you submit and is not retained
                  beyond handling your request. A professor's request to correct or remove their
                  page also requires an email address, so we can confirm it with them.
                </li>
                <li>
                  <strong>Bookmarks:</strong> when you are signed in and bookmark a professor or
                  course, we store your Google account id, the item type (professor or course),
                  the professor or course identifier, and a timestamp in our database. Each
                  account is capped at 200 bookmarks. These records are retained on our servers
                  — see <em>How We Store Your Information</em> below.
                </li>
                {RATE_ENABLED && (
                <li>
                  <strong>Ratings:</strong> you do not need to sign in to submit a rating. We
                  store your answers (professor, course, term, overall rating, difficulty, weekly hours,
                  grade, and an optional comment), a keyed hash of a random device ID that your
                  browser keeps, keyed hashes of your IP address and of its /24 (IPv4) or /64
                  (IPv6) network, the network type (campus, mobile carrier, Private Relay,
                  datacenter, other, or unknown), and how long the form took to fill in. The hashes use
                  a secret key that we keep private, so they cannot be matched to an address
                  or device without it. This data is <strong>pseudonymous, not anonymous</strong>:
                  it is not tied to your name or email, but the device ID hash links ratings
                  from the same device to each other. Comment text is also sent to OpenAI's
                  moderation service, which checks it for abuse before it is stored. If a rating is
                  held for review, its answers and comment, and why it was held, are also sent to
                  Groq, where an automated reviewer checks it. Recent ratings and comments for the same
                  professor go with it as context. The reviewer can approve a held rating, but
                  it never removes one: only our team does. See{' '}
                  <em>Retention of Ratings</em> in Section 4 for how long each item is kept.
                </li>
                )}
              </ul>
              <p>
                We do <strong>not</strong> log your search queries, which professor or course
                pages you viewed, or any other browsing activity on our servers.
                {RATE_ENABLED ? ' The one exception is the time taken to fill in the rating form, stored with a rating you submit.' : ''} The analytics
                providers listed under <em>Third-Party Services</em> collect their own data
                about your visit.
              </p>
            </section>

            <section className="terms-section">
              <h2>3. How We Use Your Information</h2>
              <p>The information we collect is used solely to:</p>
              <ul>
                <li>Authenticate your identity and confirm your <code>@husky.neu.edu</code> affiliation</li>
                <li>Display your name and profile photo in the navigation bar while signed in</li>
                <li>Save and display the professors and courses you bookmark</li>
                <li>Apply rate limits across the site so automated traffic cannot overwhelm it</li>
                {RATE_ENABLED && (<>
                <li>Prevent duplicate or fraudulent ratings</li>
                <li>Count the ratings students submit and show them on professor pages</li>
                </>)}
              </ul>
              <p>
                We do not sell, rent, or share your personal information with third parties for
                their own use, and we do not build profiles of individual users.
                {RATE_ENABLED && (<>
                {' '}The rating
                device ID links one device's ratings to each other, to catch duplicate and
                fraudulent ratings and to limit abuse.
                </>)}
              </p>
            </section>

            <section className="terms-section">
              <h2>4. How We Store Your Information</h2>
              <p>
                Your sign-in information is encoded in a JWT (JSON Web Token). During the
                Google OAuth handshake, short-lived <code>httpOnly</code> cookies are used
                to carry the flow; once complete, the resulting JWT is stored in your
                browser's <code>localStorage</code> and the handshake cookies are cleared.
                The token expires automatically after 7 days. RateMyHusky does not maintain
                user accounts or profiles; the only per-user data we store server-side is your
                bookmarks{RATE_ENABLED ? ' and your ratings (which are pseudonymous)' : ''}, described below.
              </p>
              <p>
                Signing out deletes the token from your browser immediately.
              </p>
              <p>
                If you bookmark a professor or course, that bookmark is stored
                server-side in our database, keyed to your Google account id, along with the
                item type, the professor or course identifier, and a timestamp. Bookmarks
                persist across sign-ins until you remove them or request deletion — see{' '}
                <em>Your Rights &amp; Choices</em>.
              </p>
              {RATE_ENABLED && (<>
              <p>
                If you submit a rating, it is stored in our database with the data listed under
                Ratings in Section 2. A rating is not tied to a Google account.
              </p>
              <p>
                <strong>Retention of Ratings.</strong> The keyed IP and network hashes are
                kept for 30 days and then deleted in routine cleanup; the rating itself stays,
                and so do the network type and the form fill time. The device
                ID hash and a hash of the comment text (used to spot copied comments) live with
                the rating and are deleted with it, with one exception: when we remove a rating for
                abuse, we keep its device ID hash to block further abuse from that device, and
                its IP hash for 30 days after removal. IP hashes from campus networks, mobile
                networks and Private Relay are never kept this way. Comments are stored but are not shown
                publicly. A rating is kept until we remove it or you ask us to delete it (see{' '}
                <em>Your Rights &amp; Choices</em>).
              </p>
              </>)}
              <p>
                Our database is a self-hosted PostgreSQL server on Oracle Cloud Infrastructure in
                the United States (US East – Ashburn), the API runs on Railway, and the site is
                served through Vercel. Each of these
                providers processes data on our behalf under its own terms; see{' '}
                <em>Third-Party Services</em>.
              </p>
            </section>

            <section className="terms-section">
              <h2>5. Third-Party Services</h2>
              <p>RateMyHusky integrates with the following third-party services that may
                collect data under their own privacy policies:</p>
              <ul>
                <li>
                  <strong>Google OAuth 2.0</strong>: handles authentication. Your use of
                  Google sign-in is governed by{' '}
                  <a
                    href="https://policies.google.com/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Vercel Analytics &amp; Speed Insights</strong>: collects anonymous
                  page view and performance metrics. No personally identifiable information is
                  included. Subject to{' '}
                  <a
                    href="https://vercel.com/legal/privacy-policy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Vercel's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Google Analytics</strong>: collects anonymous usage data such as page
                  views, engagement, and general geographic region to help us understand
                  how the service is used and improve it. Google Analytics may use cookies to
                  distinguish unique users. No personally identifiable information is shared
                  with Google Analytics. Subject to{' '}
                  <a
                    href="https://policies.google.com/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Resend</strong>: delivers email for the feedback form. When you submit
                  feedback, your message and any optional reply email address are transmitted
                  through Resend to reach our team. Subject to{' '}
                  <a
                    href="https://resend.com/legal/privacy-policy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Resend's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Cloudflare Turnstile</strong>: a CAPTCHA that protects the feedback
                  form{RATE_ENABLED ? ' and the rating form' : ''} from automated abuse. It may process your IP address and browser signals
                  to verify you are human. Subject to{' '}
                  <a
                    href="https://www.cloudflare.com/privacypolicy/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Cloudflare's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Vercel, Railway &amp; Oracle Cloud Infrastructure</strong>: host the site, the API,
                  and the database respectively. As part of normal infrastructure operation they
                  may log request data such as IP addresses and user-agent strings. Subject to{' '}
                  <a
                    href="https://vercel.com/legal/privacy-policy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Vercel's
                  </a>
                  ,{' '}
                  <a
                    href="https://railway.com/legal/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Railway's
                  </a>
                  , and{' '}
                  <a
                    href="https://www.oracle.com/legal/privacy/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Oracle's
                  </a>{' '}
                  privacy policies.
                </li>
                <li>
                  <strong>RateMyProfessors, Northeastern faculty and award pages, the Northeastern course catalog and course schedule (NUBanner) &amp; Reddit</strong>: these are data sources only. We do not send any user
                  data to these services.
                </li>
                {RATE_ENABLED && (<>
                <li>
                  <strong>OpenAI Moderation</strong>: the text of an optional rating comment is
                  sent to OpenAI's moderation service to check it for abuse before the rating is
                  stored. Subject to{' '}
                  <a
                    href="https://openai.com/policies/privacy-policy/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    OpenAI's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Groq</strong>: the answers and comments of ratings held for review, why
                  they were held, and recent ratings and comments for the same professor, are sent to Groq for an
                  automated check. Comments, including public RateMyProfessors comments, are also used to
                  suggest nicknames that help search find a professor. Nicknames are used only in search and are
                  never shown. Subject to{' '}
                  <a
                    href="https://groq.com/privacy-policy/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Groq's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>ipinfo</strong>: we use ipinfo's IP address database to tell what
                  type of network a rating came from. The database is used locally on our
                  server, and no data about you is sent to ipinfo.
                </li>
                </>)}
              </ul>
            </section>

            <section className="terms-section">
              <h2>6. Cookies &amp; Local Storage</h2>
              <p>
                During the Google OAuth sign-in flow, short-lived <code>httpOnly</code> cookies
                are set to carry your return destination through the handshake; they are not used
                for tracking and are cleared once sign-in completes.
                {RATE_ENABLED && (<>
                {' '}If you use the rating
                form, we also set a long-lived <code>rmh_device</code> cookie (up to 400 days,
                <code>httpOnly</code>) holding a random device ID; it is used to count each
                device's rating once, let you update it, and limit abuse.
                </>)}
                {' '}Google Analytics may set
                cookies (e.g., <code>_ga</code>, <code>_gid</code>) to distinguish unique users
                and track anonymous session data. You can opt out of Google Analytics tracking by
                installing the{' '}
                <a
                  href="https://tools.google.com/dlpage/gaoptout"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Google Analytics Opt-out Browser Add-on
                </a>.
              </p>
              <p>
                <code>localStorage</code> is used to store your JWT session token
                (<code>auth_token</code>), your theme, your catalog view mode, and flags for
                on-page tips you have dismissed. <code>sessionStorage</code> holds the review tab
                you last opened, and is cleared when you close the tab. None of this data is
                synced to our servers{RATE_ENABLED ? (<>, with one exception: the rating form also keeps a copy of
                its device ID (<code>rmh_device</code>) in <code>localStorage</code>, and that
                copy is sent to our servers when you use the rating form</>) : ''}.
              </p>
            </section>

            <section className="terms-section">
              <h2>7. Your Rights &amp; Choices</h2>
              <p>
                We keep little data, and much of it is under your direct control.
                The rights below describe what you can request and how to exercise them:
              </p>
              <ul>
                <li>
                  <strong>Right to access:</strong> you may request a copy of the data we hold
                  that is associated with you. In practice this is limited to your
                  bookmarks{RATE_ENABLED ? ' and your ratings' : ''}; your sign-in details and preferences live only in your own
                  browser and are not accessible to us.
                  {RATE_ENABLED && (<>
                  {' '}Ratings are not tied to an account, so
                  to ask for yours, email{' '}
                  <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a> with the
                  device ID from the browser you rated with (see Right to deletion below). We
                  look them up by hand.
                  </>)}
                </li>
                <li>
                  <strong>Right to deletion:</strong> you can <strong>sign out</strong> at any
                  time to immediately delete your JWT token from your browser, and{' '}
                  <strong>clear localStorage</strong> in your browser settings to remove your
                  session token and stored preferences. You can remove an individual bookmark at
                  any time by un-bookmarking it. To delete everything we hold for your account,
                  sign in and submit a <strong>Account Deletion</strong> request through the
                  feedback form: an email address is required, and your signed-in account
                  identifier is included so we can verify your identity and delete the records
                  tied to your account.
                  {RATE_ENABLED && (<>
                  {' '}To delete ratings, which are not tied to an account,
                  email{' '}
                  <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a> with the
                  device ID from the browser you rated with: it is the value of the{' '}
                  <code>rmh_device</code> key in this site's <code>localStorage</code> (browser
                  developer tools, Application or Storage tab). We find those ratings by hand
                  and delete them.
                  </>)}
                  {' '}({RATE_ENABLED ? 'For everything else you' : 'You'} may also email{' '}
                  <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a>, though
                  because we never store your email address, we can only act on a request we can
                  tie to your account — submitting the form while signed in is the reliable path.)
                </li>
                <li>
                  <strong>Right to correction:</strong> your name, email, and photo come
                  directly from Google and are never stored on our servers, so corrections to
                  them are made through your Google account. Your Google account id also comes
                  from Google and cannot be edited; we store it with your bookmarks, and a Data
                  Deletion Request removes it (see Right to deletion above).
                  If you believe professor or course data displayed on the site is inaccurate,
                  you can report it through the feedback form under "Wrong or Missing Data."
                </li>
                <li>
                  <strong>Right to raise a concern:</strong> you may contact us at any time at{' '}
                  <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a> with any
                  question or complaint about how your data is handled.
                </li>
              </ul>
              <p>
                Note that there is no account to delete. Once your token is cleared, no personal
                data remains in our systems except for any bookmarks{RATE_ENABLED ? ' and ratings' : ''}, which remain
                until you request their deletion.
              </p>
            </section>

            <section className="terms-section">
              <h2>8. Information About Professors &amp; Instructors</h2>
              <p>
                Most of the personal information on RateMyHusky is about professors and
                instructors rather than about the students using the site, so it is worth
                stating plainly what we publish and where it comes from:
              </p>
              <ul>
                <li>
                  Name, department, and college, together with metrics we compute from the
                  underlying data (average rating, difficulty, would-take-again, and
                  department comparisons).
                </li>
                <li>
                  The courses and terms they taught since {BANNER_SINCE}, with the average class
                  size of each course they taught, taken from Northeastern's public course
                  schedule.
                </li>
                <li>
                  Ratings and written reviews from
                  RateMyProfessors{RATE_ENABLED ? ", and ratings submitted by students through RateMyHusky's own rating form" : ''}.
                </li>
                <li>
                  A profile photo, taken from the public Northeastern faculty and college
                  directory pages that publish it.
                </li>
                <li>
                  Excerpts of public Reddit posts and comments that mention the professor, shown
                  with the subreddit and a link to the original, along with a sentiment label our
                  pipeline derives from the text. We do not display or store Reddit usernames.
                </li>
                <li>
                  Teaching awards Northeastern has announced, with the year and a link to the
                  announcement, taken from the award pages and news posts Northeastern
                  publishes.
                </li>
              </ul>
              <p>
                We publish no contact details, no course rosters, and nothing that is not already
                public in the sources above.
              </p>
              <p>
                <strong>Removal requests.</strong> If you are a professor or instructor and want
                your information taken down, email{' '}
                <a href="mailto:legal@ratemyhusky.com">legal@ratemyhusky.com</a> or use the
                feedback form (&ldquo;Data Deletion&rdquo;), and include
                your Northeastern email address. We confirm each
                request at that address before acting on it, so that no one can remove or
                change a professor's information by using their name; a request without a
                Northeastern email address cannot be verified or answered. We honor confirmed
                requests. Once processed, your name is added to a
                removal list that every data loader checks before writing, so a weekly refresh
                cannot reinstate you, and the rows already loaded — your page, your imported ratings and
                comments, your course-schedule history, your Reddit mentions, and the evidence
                corpus built from them — are
                deleted.
                {RATE_ENABLED ? ' Ratings that students submitted through our own rating form about you are deleted on request; our team handles those by hand.' : ''} Two limits are worth being straight about: we cannot remove your data
                from RateMyProfessors or Reddit themselves, and our own private source
                files can still contain your rows until the upstream source stops publishing
                them, though nothing published on the site can reach them. If you
                need removal from a source itself, contact that source directly.
              </p>
              <p>
                <strong>Corrections.</strong> If something on your page is wrong or missing, such
                as your photo, department, college, courses, or awards, contact us the same way,
                with your Northeastern email address, and we will correct it after confirming the
                request with you.
              </p>
            </section>

            <section className="terms-section">
              <h2>9. Children's Privacy</h2>
              <p>
                RateMyHusky is intended for Northeastern University students (aged 18 and
                older) and is not directed at children. We do not knowingly collect personal
                information from anyone under the age of 18. If you believe a minor has
                provided us with personal information, please contact us at{' '}
                <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a>.
              </p>
            </section>

            <section className="terms-section">
              <h2>10. Changes to This Policy</h2>
              <p>
                We may update this Privacy Policy from time to time. The effective date at the
                top of this page will be updated when changes are made. Continued use of
                RateMyHusky after changes are posted constitutes your acceptance of the
                revised Policy.
              </p>
            </section>

            <section className="terms-section terms-section--last">
              <h2>11. Contact</h2>
              <p>
                If you have questions about this Privacy Policy or want to report a concern,
                please email us at{' '}
                <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a> or use
                the feedback form available at the bottom-right of any page on RateMyHusky.
              </p>
            </section>
          </div>
        </div>
      </main>
      <Footer />
    </div>
  );
};

export default Privacy;
