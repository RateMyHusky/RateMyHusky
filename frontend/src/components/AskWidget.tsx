import { useState, useRef, useEffect } from 'react';
import './AskWidget.css';

type Msg = { id: number; from: 'bot' | 'user'; text: string };

const GREETING: Msg = {
  id: 0,
  from: 'bot',
  text: "Hi — I'm the RateMyHusky assistant. Ask me about a professor, a course, or how the site works.",
};

/* Entry point for the site assistant. Open/close is driven entirely by the
   `open` class — see AskWidget.css for the animation.

   The container is a div, not a button, so the controls and the chat form can
   be real interactive elements nested inside it.

   NOT WIRED UP: submitting echoes the message and returns a fixed placeholder.
   To connect it, call askChat() from src/api/api.ts — the backend Ask pipeline
   already exists at /api/chat. Note it 401s for signed-out users. */
const AskWidget = () => {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState<Msg[]>([GREETING]);
  const [draft, setDraft] = useState('');
  const logRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, open]);

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

  const send = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) return;
    setMessages(m => [
      ...m,
      { id: m.length, from: 'user', text },
      { id: m.length + 1, from: 'bot', text: "I'm not connected to anything yet — this is the interface only." },
    ]);
    setDraft('');
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

      <div className="ask-panel" aria-hidden={!open}>
        <header className="ask-panel-head">
          <span className="ask-panel-title">Ask RateMyHusky</span>
        </header>

        <div className="ask-panel-log" ref={logRef}>
          {messages.map(m => (
            <p key={m.id} className={`ask-msg ask-msg-${m.from}`}>
              {m.text}
            </p>
          ))}
        </div>

        <form className="ask-panel-form" onSubmit={send}>
          <input
            className="ask-panel-input"
            value={draft}
            onChange={e => setDraft(e.target.value)}
            placeholder="Ask a question…"
            aria-label="Your question"
            tabIndex={open ? 0 : -1}
          />
          <button
            className="ask-panel-send"
            type="submit"
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
