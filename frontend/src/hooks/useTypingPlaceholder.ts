import { useEffect, useState } from 'react';
import { useMediaQuery } from './useMediaQuery';

/* Types each example out and deletes it again, cycling from a random start. While paused or
   under reduced motion it shows staticText. With quote, a typed example reads `Search for "..."`
   and the gap between examples shows staticText; without it, the raw text shows. */
export function useTypingPlaceholder(examples: string[], staticText: string, paused: boolean, quote = true): string {
  const [placeholder, setPlaceholder] = useState('');
  const reduced = useMediaQuery('(prefers-reduced-motion: reduce)');

  useEffect(() => {
    if (paused || reduced) return;

    let currentExampleIndex = Math.floor(Math.random() * examples.length);
    let currentText = '';
    let isDeleting = false;
    let typingSpeed = 100;

    const type = () => {
      const fullText = examples[currentExampleIndex];
      if (isDeleting) {
        currentText = fullText.substring(0, currentText.length - 1);
        typingSpeed = 50;
      } else {
        currentText = fullText.substring(0, currentText.length + 1);
        typingSpeed = 100;
      }
      setPlaceholder(quote && currentText ? `Search for "${currentText}"` : currentText);
      if (!isDeleting && currentText === fullText) {
        isDeleting = true;
        typingSpeed = 2000; // Pause at end
      } else if (isDeleting && currentText === '') {
        isDeleting = false;
        currentExampleIndex = (currentExampleIndex + 1) % examples.length;
        typingSpeed = 500; // Pause before next
      }
      timeoutId = setTimeout(type, typingSpeed);
    };

    let timeoutId = setTimeout(type, typingSpeed);
    return () => { clearTimeout(timeoutId); setPlaceholder(''); };
  }, [paused, reduced, examples, quote]);

  if (paused || reduced) return staticText;
  // Between examples the text is empty: show the plain prompt, not `Search for ""`.
  return quote ? placeholder || staticText : placeholder;
}
