export interface HashOptions {
  algorithm: string;
  encoding: string;
}

export type HashResult = {
  value: string;
  length: number;
};

export function computeHash(data: string, options?: HashOptions): string {
  return data.length.toString();
}

export function formatAmount(amount: number, currency: string = "USD"): string {
  return `${currency} ${amount.toFixed(2)}`;
}

export const DEFAULT_OPTIONS: HashOptions = {
  algorithm: "sha256",
  encoding: "hex",
};
