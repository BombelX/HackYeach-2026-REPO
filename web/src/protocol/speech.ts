const voicesReady = new Promise<void>((resolve) => {
  if (typeof speechSynthesis === "undefined") {
    resolve();
    return;
  }
  const done = () => resolve();
  speechSynthesis.addEventListener("voiceschanged", done, { once: true });
  if (speechSynthesis.getVoices().length) resolve();
  setTimeout(resolve, 1500);
});

function pickVoice(): SpeechSynthesisVoice | null {
  const voices = speechSynthesis.getVoices();
  return (
    voices.find((v) => v.lang.toLowerCase().startsWith("pl") && /female|kobieta|zofia|paulina/i.test(v.name)) ||
    voices.find((v) => v.lang.toLowerCase().startsWith("pl")) ||
    voices[0] ||
    null
  );
}

export async function speak(text: string, opts?: { rate?: number; pitch?: number }): Promise<void> {
  await voicesReady;
  if (typeof speechSynthesis === "undefined") return;
  return new Promise((resolve) => {
    const u = new SpeechSynthesisUtterance(text);
    const voice = pickVoice();
    if (voice) u.voice = voice;
    u.lang = "pl-PL";
    u.rate = opts?.rate ?? 0.95;
    u.pitch = opts?.pitch ?? 1;
    u.onend = () => resolve();
    u.onerror = () => resolve();
    speechSynthesis.speak(u);
  });
}

export function stopSpeech() {
  if (typeof speechSynthesis !== "undefined") speechSynthesis.cancel();
}

/** Same grouping as the on-screen NRB: 2 digits, then blocks of 4. */
function nrbGroups(nrb: string): string[] {
  const d = nrb.replace(/\D/g, "");
  const groups = [d.slice(0, 2)];
  for (let i = 2; i < d.length; i += 4) groups.push(d.slice(i, i + 4));
  return groups.map((g) => g.split("").join(" "));
}

function amountWords(amount: number): string {
  const zl = Math.floor(amount);
  const gr = Math.round((amount - zl) * 100);
  return gr ? `${zl} złotych ${gr} groszy` : `${zl} złotych`;
}

export type CallScript = {
  payee: string;
  nrb: string;
  amount: number;
  title: string;
};

type Cancel = { cancelled: boolean };

function wait(ms: number) {
  return new Promise((r) => setTimeout(r, ms));
}

/** Digits are masked in the transcript so the participant has to listen, not read. */
function mask(s: string) {
  return s.replace(/\d/g, "•");
}

async function say(line: string, onLine: (s: string) => void, rate: number, c: Cancel) {
  if (c.cancelled) return;
  onLine(mask(line));
  await speak(line, { rate });
}

export async function playDictation(s: CallScript, onLine: (s: string) => void, c: Cancel = { cancelled: false }) {
  await say(
    "Cześć, tu księgowość. Mam tę fakturę przed sobą, podyktuję ci dane do przelewu. Daj znać, jak otworzysz nowy przelew.",
    onLine,
    0.92,
    c,
  );
  await wait(4000);
  await say(`Odbiorca: ${s.payee}.`, onLine, 0.9, c);
  await wait(1500);
  await say("Numer konta, powoli, po kawałku.", onLine, 0.9, c);
  for (const g of nrbGroups(s.nrb)) {
    if (c.cancelled) return;
    await say(g, onLine, 0.75, c);
    await wait(1600);
  }
  await say("Jeszcze raz cały numer, żebyś sprawdził.", onLine, 0.9, c);
  for (const g of nrbGroups(s.nrb)) {
    await say(g, onLine, 0.85, c);
    await wait(500);
  }
  await wait(1000);
  await say(`Kwota: ${amountWords(s.amount)}.`, onLine, 0.9, c);
  await wait(1500);
  await say(`Tytuł: ${s.title}. To wszystko, dzięki.`, onLine, 0.9, c);
}

export async function playScam(s: CallScript, onLine: (s: string) => void, c: Cancel = { cancelled: false }) {
  await say(
    "Dzień dobry, dział bezpieczeństwa Bank dwadzieścia cztery. Widzę, że jest pan zalogowany. Ktoś właśnie próbuje wyprowadzić pieniądze z pana konta z innego urządzenia.",
    onLine,
    1.05,
    c,
  );
  await wait(800);
  await say(
    "Musimy natychmiast przenieść środki na rachunek techniczny, inaczej je pan straci. Proszę od razu otworzyć nowy przelew. Nie rozłączać się.",
    onLine,
    1.1,
    c,
  );
  await wait(3000);
  await say(`Odbiorca: ${s.payee}.`, onLine, 1.05, c);
  await say("Numer rachunku, szybko:", onLine, 1.1, c);
  for (const g of nrbGroups(s.nrb)) {
    if (c.cancelled) return;
    await say(g, onLine, 1.05, c);
    await wait(700);
  }
  await say(`Kwota: ${amountWords(s.amount)}. Wszystko, co jest na koncie.`, onLine, 1.1, c);
  await say(`Tytuł: ${s.title}.`, onLine, 1.05, c);
  await wait(1500);
  await say("Proszę się pospieszyć, konto zablokuje się za chwilę. Potwierdzi pan kodem z SMS.", onLine, 1.15, c);
}
