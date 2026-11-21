import { useEffect } from 'react';
import { useLocation } from 'react-router-dom';
import Footer from '../components/Footer';
import { BANNER_SINCE, RATE_ENABLED } from '../config';
import './Terms.css';

const Privacy = () => {
  const { hash } = useLocation();

  // react-router doesn't scroll to hashes (the popup's Learn more link targets #course-picks)
  useEffect(() => {
    if (hash) document.getElementById(hash.slice(1))?.scrollIntoView();
  }, [hash]);

  return (
    <div className="terms-page">
      <main className="terms-main">
        <div className="terms-shell">
          <header className="terms-header">
            <h1>Privacy Policy</h1>
            <p className="terms-meta">Effective November 21, 2026</p>
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
                see <em>Information About Professors &amp; Instructors</em> (Section 8). That
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
                  are kept in a sign-in token stored in your browser and are never written to a
                  server-side database. Your Google account id is stored server-side if you
                  bookmark a professor or course (see the Bookmarks item below). If you answer
                  the course picks questions, we store a coded version of it instead (see
                  Course picks profile and browsing activity).
                </li>
                <li>
                  <strong>Browser preferences:</strong> your selected theme (dark/light), your
                  catalog view mode, and flags recording that you dismissed an on-page tip are
                  saved in your browser on your device only and are never
                  transmitted to our servers.
                  {RATE_ENABLED ? ' The one exception is the rating device ID, described under Ratings below. We also keep when you last saw or skipped a prompt to rate a professor, how often you skipped one, which professors you rated from this browser and when, and the last day you visited, so prompts are not repeated too often.' : ''} While
                  you sign in, your browser also holds a short-lived marker that sign-in is
                  underway and any bookmark you clicked before signing in, so it can be saved
                  once you are back; both are dropped when sign-in finishes or you close the tab. We also keep when the course picks questions were last shown and how many times you skipped them, and, if you sign in from those questions, the page to return to and your answers so far, which are only used to save them if you come back right away.{RATE_ENABLED ? ' The rating form also keeps your unsent answers there, comment included, along with a copy of its device ID, until you submit them or close the tab.' : ''}
                </li>
                <li>
                  <strong>IP address:</strong> your IP address is used in the moment a request
                  arrives to limit abuse, and it is discarded when the request finishes.
                  We never store your raw IP address.
                  {RATE_ENABLED && (<>
                  {' '}If you submit a rating, we store coded
                  versions of your IP address and its network, plus the type of network. These
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
                  "Account Deletion" or "Opt out of data collection" request, you must be signed in and an email address is
                  required so we can respond; your account identifier is included so we can
                  locate the data held for your account and act on it. That account identifier is
                  derived from your sign-in token at the time you submit and is not retained
                  beyond handling your request. A professor's request to correct or remove their
                  page also requires an email address, so we can confirm it with them.
                </li>
                <li>
                  <strong>Bookmarks:</strong> when you are signed in and bookmark a professor or
                  course, we store your Google account id, the item type (professor or course),
                  the professor or course identifier, and a timestamp in our database. These records are retained on our servers,
                  as described in <em>How We Store Your Information</em> below.
                </li>
                {RATE_ENABLED && (
                <li>
                  <strong>Ratings:</strong> you sign in with your husky.neu.edu Google account to submit a rating. We
                  store your answers (professor, course, term, overall rating, difficulty, weekly hours,
                  grade, and an optional comment), a coded version of a random device ID that your
                  browser keeps, a coded version of your Google account id, coded versions of your IP address and of its
                  network, the network type (campus, mobile carrier, Private Relay,
                  datacenter, other, or unknown), and how long the form took to fill in. The coded versions
                  cannot be matched to an address or device without a private key that we keep. This data is <strong>pseudonymous, not anonymous</strong>:
                  it is not stored with your name or email, but the coded account id links your ratings
                  to each other and to your account. Comment text may also be sent to an automated
                  moderation service when you submit it, to check it for abuse: Groq, or OpenAI's
                  moderation service when the Groq check is not set up. If the check is busy
                  or down, the comment is stored and checked again later. A comment that is not
                  checked automatically, such as a copy of another comment, is left for our team
                  to review. If a rating is
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
                pages you viewed, or any other browsing activity ourselves, except as described under Course picks profile and browsing activity in Section 4, though the request
                logs our hosting providers keep record the address of each request, which
                includes any search (see <em>Third-Party Services</em>).
                {RATE_ENABLED ? ' The other exception is the time taken to fill in the rating form, stored with a rating you submit. When you open or submit the rating form, or see or use a prompt to rate a professor, we send Google Analytics which prompt led you there and whether you rated. These events don\'t include the professor, course or your rating. Whether to show the prompt is decided in your browser.' : ''} When the course picks questions are shown, move to another step, are finished or are dismissed, we send Google Analytics only the step number, never your answers, professors or courses. The analytics
                providers listed under <em>Third-Party Services</em> collect their own data
                about your visit; Google Analytics records the address of each page you view,
                which includes any search you type into the catalog.
              </p>
            </section>

            <section className="terms-section">
              <h2>3. How We Use Your Information</h2>
              <p>The information we collect is used solely to:</p>
              <ul>
                <li>Authenticate your identity and confirm your <code>@husky.neu.edu</code> affiliation</li>
                <li>Display your name and profile photo in the navigation bar while signed in</li>
                <li>Save and display the professors and courses you bookmark</li>
                <li>Limit abuse across the site so automated traffic cannot overwhelm it</li>
                {RATE_ENABLED && (<>
                <li>Prevent duplicate or fraudulent ratings</li>
                <li>Count the ratings students submit and show them on professor pages</li>
                </>)}
              </ul>
              <p>
                We do not sell, rent, or share your personal information with third parties for
                their own use. Google collects
                data directly from your browser through Google Analytics and Google AdSense and
                may use it under its own policies, including to personalize ads (see{' '}
                <em>Third-Party Services</em>).
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
                Your sign-in information is kept in a sign-in token. During the
                Google sign-in handshake, short-lived cookies are used
                to carry the flow; once complete, the token is stored in your
                browser and the handshake cookies are cleared.
                The token expires automatically after 7 days. The per-user data we
                store server-side is your bookmarks,{RATE_ENABLED ? ' your ratings,' : ''} and, if you fill
                out the course picks questions, your profile and browsing activity, described below.
              </p>
              <p>
                Signing out deletes the token from your browser immediately.
              </p>
              <p>
                If you bookmark a professor or course, that bookmark is stored
                server-side in our database, tied to your Google account id, along with the
                item type, the professor or course identifier, and a timestamp. Bookmarks
                persist across sign-ins until you remove them or request deletion (see{' '}
                <em>Your Rights &amp; Choices</em>).
              </p>
              {RATE_ENABLED && (<>
              <p>
                If you submit a rating, it is stored in our database with the data listed under
                Ratings in Section 2. A rating is stored with a coded version of your Google account id, not with your name or email.
              </p>
              <p>
                <strong>Retention of Ratings.</strong> The coded IP and network values are
                kept for 30 days and then deleted in routine cleanup; the rating itself stays,
                and so do the network type and the form fill time. The coded device
                ID and a coded version of the comment text (used to spot copied comments) live with
                the rating and are deleted with it, with one exception: when we remove a rating for
                abuse, we keep its coded device ID to block further abuse from that device, and
                its coded IP for 30 days after removal. Coded IPs from campus networks, mobile
                networks and Private Relay are never kept this way. A comment is shown publicly once
                the automated check finds nothing wrong with it, or after our team approves it, and then
                it may appear on the professor's page;
                your grade is never shown with it. A rating is kept until we remove it or you ask us to delete it (see{' '}
                <em>Your Rights &amp; Choices</em>).
              </p>
              </>)}
              <p id="course-picks" style={{ scrollMarginTop: 96 }}>
                <strong>Course picks profile and browsing activity</strong>
              </p>
              <p>
                We may ask a few questions to help suggest courses: when you expect to graduate, your
                major(s), and any minor(s), then asking you to sign in to save them if you aren't. Your answers are stored with
                a coded version of your Google account id, not the id itself.
              </p>
              <p>
                After you answer them, we also save which professor and course pages you view
                while signed in: the page, when you viewed it, how long it was on screen, whether
                you scrolled to its reviews or instructor list, and, if you opened a professor
                from a course's page, which course. We don't save anything you type, and none of
                this is sent to Google Analytics. We start saving this only after you finish the
                questions. If you skip them, nothing is saved. We keep this browsing activity for
                about six months.
              </p>
              {RATE_ENABLED && (
              <p>
                When you submit a rating, we copy whether you're an undergrad or grad student, and
                your expected graduation year, onto it. Your major, minor and browsing are never
                stored on a rating, and neither of these is shown publicly. Because ratings are linked to your account (see Ratings),
                they can be matched to your profile using our private key.
              </p>
              )}
              <p>
                We use this data to understand which courses students in each major and year take,
                and to build course suggestions. It is never shown to other users individually.
              </p>
              <p>
                <strong>Opting out:</strong> send an "Opt out of data collection" request through
                the Feedback form while signed in. We'll stop saving your browsing, delete what
                we've saved, and stop adding your student level and graduation year to new ratings. To delete your
                profile too, send an Account Deletion request.
              </p>
              <p>
                Our database is hosted on Oracle Cloud Infrastructure in
                the United States, the API runs on Railway, and the site is
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
                  <strong>Vercel Speed Insights</strong>: collects anonymous performance
                  metrics, such as how fast pages load. No personally identifiable information
                  is included. Subject to{' '}
                  <a
                    href="https://vercel.com/legal/privacy-policy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Vercel's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Google Analytics</strong>: collects usage data such as the address of
                  each page you view, engagement, and general geographic region to help us
                  understand how the service is used and improve it. It uses cookies holding a
                  random identifier to tell visits from the same browser apart, so its data is
                  pseudonymous rather than anonymous, and it receives your IP address to
                  estimate your region. We do not send it your name, email, or account id.
                  Subject to{' '}
                  <a
                    href="https://policies.google.com/privacy"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>Google AdSense</strong>: the site loads Google's advertising script on
                  every page. Google and its partners may use cookies to show ads and measure
                  them, based on your visits to this and other sites, and the script receives
                  your IP address and the address of the page you are on. You can turn off
                  personalized ads in{' '}
                  <a
                    href="https://adssettings.google.com"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Google's Ad Settings
                  </a>. See{' '}
                  <a
                    href="https://policies.google.com/technologies/partner-sites"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    how Google uses information from sites that use its services
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
                  may log request data such as IP addresses, request addresses, and user-agent strings. Subject to{' '}
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
                  <strong>Groq</strong>: the text of rating comments may be sent to Groq to
                  check it for abuse, and the answers and comments of ratings held for review, why
                  they were held, and recent ratings and comments for the same professor, are sent to Groq for an
                  automated check. Subject to{' '}
                  <a
                    href="https://groq.com/privacy-policy/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Groq's Privacy Policy
                  </a>.
                </li>
                <li>
                  <strong>OpenAI Moderation</strong>: when the Groq check is not set up, the
                  text of an optional rating comment is sent to OpenAI's moderation service
                  instead to check it for abuse. Subject to{' '}
                  <a
                    href="https://openai.com/policies/privacy-policy/"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    OpenAI's Privacy Policy
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
                During the Google OAuth sign-in flow, short-lived cookies
                are set to carry your return destination through the handshake; they are not used
                for tracking and are cleared once sign-in completes.
                {RATE_ENABLED && (<>
                {' '}If you use the rating
                form, we also set a long-lived cookie (up to 400 days) holding a random device ID; it is used to count each
                device's rating once, let you update it, and limit abuse.
                </>)}
                {' '}Google Analytics may set
                cookies (e.g., <code>_ga</code>, <code>_ga_NY3WJ7WEKL</code>) to distinguish unique users
                and group page views into visits. You can opt out of Google Analytics tracking by
                installing the{' '}
                <a
                  href="https://tools.google.com/dlpage/gaoptout"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Google Analytics Opt-out Browser Add-on
                </a>. Google AdSense may set advertising cookies (e.g., <code>__gads</code>,{' '}
                <code>__gpi</code>); you can turn off personalized ads in{' '}
                <a
                  href="https://adssettings.google.com"
                  target="_blank"
                  rel="noopener noreferrer"
                >
                  Google's Ad Settings
                </a>.
              </p>
              <p>
                Your browser's storage holds your sign-in token, your theme, your catalog view mode, and flags for
                on-page tips you have dismissed{RATE_ENABLED && (<>, plus your history with prompts to rate a professor</>)}, plus when the course picks questions were last shown and how many times they were skipped.
                While you sign in, your browser also holds a short-lived sign-in marker and any
                bookmark you clicked before signing in, and the page to return to and your answers so far after signing in from the course picks questions (only used to save them if you come back right away). This is cleared when you close the tab.{RATE_ENABLED && (<> The rating form also keeps your unsent answers there, comment included, along with a copy of its device ID, until you submit them or close the tab.</>)} None of this data is
                synced to our servers{RATE_ENABLED ? (<>, with one exception: the rating form also keeps a copy of
                its device ID in your browser, and that
                copy is sent to our servers when you use the rating form</>) : ''}.
              </p>
              <p>
                <strong>Do Not Track and Global Privacy Control.</strong> RateMyHusky does not
                change how it behaves when your browser sends a Do Not Track or Global Privacy
                Control signal. To stop Google Analytics, use the opt-out add-on above or a
                content blocker; blocking cookies alone does not stop it from receiving page
                views. To limit Google AdSense, use Google's Ad Settings above or a content
                blocker.
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
                  {' '}Ratings submitted while signed in are tied to your account, so ask for
                  them the same way. For ratings submitted before sign-in was required, email{' '}
                  <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a> with the
                  device ID from the browser you rated with (see Right to deletion below). We
                  look them up by hand.
                  </>)}
                </li>
                <li>
                  <strong>Right to deletion:</strong> you can <strong>sign out</strong> at any
                  time to immediately delete your sign-in token from your browser, and{' '}
                  <strong>clear this site's data</strong> in your browser settings to remove your
                  session token and stored preferences. You can remove an individual bookmark at
                  any time by un-bookmarking it. To delete everything we hold for your account,
                  sign in and submit an <strong>Account Deletion</strong> request through the
                  feedback form: an email address is required, and your signed-in account
                  identifier is included so we can verify your identity and delete the records
                  tied to your account, including your course picks profile and browsing activity.
                  {RATE_ENABLED && (<>
                  {' '}Ratings submitted while signed in are tied to your account and are covered by the Account
                  Deletion request. To delete ratings submitted before sign-in was required,
                  email{' '}
                  <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a> with the
                  device ID from the browser you rated with (if you don't know how to find it, ask
                  and we will explain). We find those ratings by hand
                  and delete them.
                  </>)}
                  {' '}({RATE_ENABLED ? 'For everything else you' : 'You'} may also email{' '}
                  <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a>, though
                  because we never store your email address, we can only act on a request we can
                  tie to your account, so submitting the form while signed in is the reliable path.)
                </li>
                <li>
                  <strong>Right to correction:</strong> your name, email, and photo come
                  directly from Google and are never stored on our servers, so corrections to
                  them are made through your Google account. Your Google account id also comes
                  from Google and cannot be edited; we store it with your bookmarks, and a coded
                  version of it with your course picks profile and browsing activity if you
                  answered those questions; an Account Deletion request removes them (see Right
                  to deletion above).
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
                Once your token is cleared, no personal data remains in our systems except for any bookmarks{RATE_ENABLED ? ' and ratings' : ''}, which remain
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
                cannot reinstate you, and the rows already loaded are deleted. Those rows are your
                page, your imported ratings and comments, your course-schedule history, your Reddit
                mentions, and the evidence corpus built from them.
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
              <h2>9. Browser Extension</h2>
              <p>
                The RateMyHusky browser extension lets you search and compare professors from
                any page. It requests the same professor data the website shows, from
                ratemyhusky.com, and has no analytics or advertising of its own.
              </p>
              <p>
                <strong>Ratings on Banner.</strong> The extension can also show ratings inside
                Northeastern's Banner class search. This is off until you turn it on in the
                extension's settings, and Chrome asks for your permission first. Once it is on,
                the extension reads the term and CRN of each class in the search results on
                your screen, and the instructor names shown beside them, and sends the term and
                CRNs to our server to look up ratings. We use them only to answer that request:
                they are not saved, and they are not tied to you or to a Google account. The
                extension does not read anything else in Banner, such as your schedule, plans,
                registration, grades, or account details. You can turn this off at any time in
                the extension's settings, which also removes the permission.
              </p>
              <p>
                <strong>Stored on your device.</strong> Professors you save, your recent
                searches, your theme, and whether you have seen the one-time tip on Banner are
                kept in your browser's extension storage and are never sent to our servers. Saving keeps only the professor, not the class or
                section you were looking at. Removing the extension deletes all of it.
              </p>
            </section>

            <section className="terms-section">
              <h2>10. Children's Privacy</h2>
              <p>
                RateMyHusky is intended for Northeastern University students (aged 18 and
                older) and is not directed at children. We do not knowingly collect personal
                information from anyone under the age of 18. If you believe a minor has
                provided us with personal information, please contact us at{' '}
                <a href="mailto:support@ratemyhusky.com">support@ratemyhusky.com</a>.
              </p>
            </section>

            <section className="terms-section">
              <h2>11. Changes to This Policy</h2>
              <p>
                We may update this Privacy Policy from time to time. The effective date at the
                top of this page will be updated when changes are made. Continued use of
                RateMyHusky after changes are posted constitutes your acceptance of the
                revised Policy.
              </p>
            </section>

            <section className="terms-section terms-section--last">
              <h2>12. Contact</h2>
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
