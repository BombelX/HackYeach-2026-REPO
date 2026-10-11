export function money(grosz: number) {
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency: "PLN",
  }).format(grosz / 100);
}
export function accountNumber(value: string) {
  return value
    .replace(/\s/g, "")
    .replace(
      /^(\d{2})(\d{4})(\d{4})(\d{4})(\d{4})(\d{4})(\d{4})$/,
      "$1 $2 $3 $4 $5 $6 $7",
    );
}
export function parseAmount(value: string): number | null {
  const cleaned = value.trim().replace(/\s/g, "").replace(",", ".");
  if (!/^\d{1,9}(\.\d{1,2})?$/.test(cleaned)) return null;
  const [whole, fraction = ""] = cleaned.split(".");
  const result = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  return result > 0 && Number.isSafeInteger(result) ? result : null;
}
export function validNrb(value: string): boolean {
  const number = value.replace(/\s/g, "");
  return (
    /^\d{26}$/.test(number) &&
    BigInt(number.slice(2) + "2521" + number.slice(0, 2)) % 97n === 1n
  );
}
export function fold(value: string) {
  return value
    .toLocaleLowerCase("pl")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/ł/g, "l");
}
export function date(value: string) {
  return new Date(value).toLocaleDateString("pl-PL", {
    day: "numeric",
    month: "long",
    year: "numeric",
  });
}
