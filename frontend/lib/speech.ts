/** Pronounce English text via the browser's built-in speech synthesis - no
 * generated audio files, same approach as the daily listening task. */
export function speak(text: string) {
  if (!text || typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  u.lang = "en-GB";
  u.rate = 0.9;
  window.speechSynthesis.speak(u);
}
