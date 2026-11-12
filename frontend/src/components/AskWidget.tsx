import { useState, useRef, useEffect } from 'react';
import { askChat, askHelp } from '../api/api';
import { loadTranscript, saveTranscript, withName } from '../utils/askWidget';
import type { WidgetMsg } from '../utils/askWidget';
import AskAnswer from './AskAnswer';
import type { AskPick } from './AskAnswer';
import './AskWidget.css';

const GREETING: WidgetMsg = {
  id: 0,
  from: 'bot',
  text: "Hi — I'm the RateMyHusky assistant. Ask how the site works, or about one professor or course at a time.",
};

const SIGN_IN_TEXT = 'Sign in with your Husky account to ask about professors and courses.';

/* Entry point for the site assistant. Open/close is driven entirely by the
   `open` class — see AskWidget.css for the animation.

   The container is a div, not a button, so the controls and the chat form can
   be real interactive elements nested inside it.

   Answers come from /api/chat (askChat / askHelp). Signed-out users get site
   help; anything else 401s and shows a sign-in prompt. */
const AskWidget = () => {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<WidgetMsg[]>(() => loadTranscript() ?? [GREETING]);
  const [draft, setDraft] = useState('');
  const [pending, setPending] = useState(false);
  const logRef = useRef<HTMLDivElement>(null);
  const seq = useRef(0);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  useEffect(() => {
    saveTranscript(messages);
  }, [messages]);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, open, pending]);

  // The homepage "Try Now" bubble asks us to open.
  useEffect(() => {
    const handler = () => setOpen(true);
    window.addEventListener('open-ask', handler);
    return () => window.removeEventListener('open-ask', handler);
  }, []);

  /* The software keyboard shrinks the visual viewport but not the layout one,
     so a position:fixed panel does not move and the keyboard lands on top of
     the input. Publish the covered height as --ask-kb; the CSS lifts and
     clamps the panel by it. On Android configs that resize the layout viewport
     instead, this measures 0 and dvh already handles it. */
  useEffect(() => {
    const vv = window.visualViewport;
    const root = document.documentElement;
    const clear = () => root.style.setProperty('--ask-kb', '0px');

    if (!vv || !open) {
      clear();
      return;
    }

    const sync = () => {
      const covered = window.innerHeight - vv.height - vv.offsetTop;
      root.style.setProperty('--ask-kb', `${Math.max(0, Math.round(covered))}px`);
    };

    sync();
    vv.addEventListener('resize', sync);
    vv.addEventListener('scroll', sync);
    return () => {
      vv.removeEventListener('resize', sync);
      vv.removeEventListener('scroll', sync);
      clear();
    };
  }, [open]);

  const nextId = (m: WidgetMsg[]) => (m.length ? m[m.length - 1].id + 1 : 0);

  // Appends the user bubble, runs the request, then appends the bot answer. A newer
  // request (or unmount) makes this one's answer stale and it is dropped.
  const ask = async (shown: string, request: () => ReturnType<typeof askChat>, question: string) => {
    setMessages(m => [...m, { id: nextId(m), from: 'user', text: shown }]);
    setPending(true);
    const reqId = ++seq.current;
    const { status, body } = await request();
    if (reqId !== seq.current || !mounted.current) return;
    setMessages(m => [...m, { id: nextId(m), from: 'bot', result: body, status, askedAt: Date.now(), question }]);
    setPending(false);
  };

  const send = (text: string) => ask(text, () => askChat(text), text);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    // The server answers a one-character question with an empty result: don't send it.
    if (text.length < 2 || pending) return;
    setDraft('');
    void send(text);
  };

  const onPick = (msg: WidgetMsg, pick: AskPick) => {
    if (pending) return;
    if (pick.kind === 'other') {
      const question = msg.question ?? '';
      void ask('No, other', () => askChat(question, true), question);
      return;
    }
    if (pick.kind === 'help') {
      const r = msg.result;
      const topics = r?.mode === 'site_help' ? r.menu : r?.mode === 'site_help_choice' ? r.options : undefined;
      const title = topics?.find(i => i.id === pick.id)?.title ?? 'How does this site work?';
      // A topic from the prompt sends its question along so the pick is logged against it.
      const from = r?.mode === 'site_help_choice' ? msg.question : undefined;
      void ask(title, () => askHelp(pick.id, from), title);
      return;
    }
    const ambiguous = msg.result?.mode === 'disambiguation' ? msg.result.ambiguous : undefined;
    void send(withName(msg.question ?? '', ambiguous, pick.pick));
  };

  const renderBot = (m: WidgetMsg) => {
    if (m.status === 401) {
      return (
        <>
          <p className="ask-answer">{SIGN_IN_TEXT}</p>
          <div className="ask-chips">
            <button
              type="button"
              className="ask-chip"
              onClick={() => window.dispatchEvent(new CustomEvent('open-signin'))}
            >
              Sign in
            </button>
            <button type="button" className="ask-chip" onClick={() => onPick(m, { kind: 'help', id: 'menu' })}>
              How does this site work?
            </button>
          </div>
        </>
      );
    }
    if (m.result) {
      return <AskAnswer result={m.result} askedAt={m.askedAt ?? 0} onPick={p => onPick(m, p)} />;
    }
    return m.text;
  };

  return (
    <div className={`ask-widget ${open ? 'open' : ''}`}>
      <button
        className="ask-widget-open"
        onClick={() => setOpen(true)}
        aria-label="Ask about RateMyHusky"
        aria-expanded={open}
        aria-hidden={open}
        tabIndex={open ? -1 : 0}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <path d="M21 11.5a8.38 8.38 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.38 8.38 0 0 1-3.8-.9L3 21l1.9-5.7a8.38 8.38 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.38 8.38 0 0 1 3.8-.9h.5a8.48 8.48 0 0 1 8 8v.5z" />
        </svg>
      </button>

      {/* inert while closed: links and chips in the hidden log stay out of the tab order. */}
      <div className="ask-panel" aria-hidden={!open} inert={!open}>
        <header className="ask-panel-head">
          <span className="ask-panel-title">Ask RateMyHusky</span>
        </header>

        <div className="ask-panel-log" ref={logRef}>
          {messages.map(m =>
            m.from === 'user' ? (
              <p key={m.id} className="ask-msg ask-msg-user">{m.text}</p>
            ) : (
              <div key={m.id} className="ask-msg ask-msg-bot">{renderBot(m)}</div>
            ),
          )}
          {pending && (
            <div className="ask-msg ask-msg-bot ask-typing" role="status" aria-label="Thinking">
              <span /><span /><span />
            </div>
          )}
        </div>

        <form className="ask-panel-form" onSubmit={submit}>
          <input
            className="ask-panel-input"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Ask about a professor, a course, or the site…"
            aria-label="Your question"
            tabIndex={open ? 0 : -1}
          />
          <button
            className="ask-panel-send"
            type="submit"
            disabled={pending}
            aria-label="Send"
            tabIndex={open ? 0 : -1}
          >
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="5" y1="12" x2="19" y2="12" />
              <polyline points="12 5 19 12 12 19" />
            </svg>
          </button>
        </form>
      </div>

      <button
        className="ask-widget-close"
        onClick={() => setOpen(false)}
        aria-label="Close the assistant"
        aria-hidden={!open}
        tabIndex={open ? 0 : -1}
      >
        <svg
          xmlns="http://www.w3.org/2000/svg"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <line x1="18" y1="6" x2="6" y2="18" />
          <line x1="6" y1="6" x2="18" y2="18" />
        </svg>
      </button>
    </div>
  );
};

export default AskWidget;
