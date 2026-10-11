export type Consents = {
  study: boolean;
  keyboard_mouse: boolean;
  face_pose: boolean;
  video: boolean;
  motion: boolean;
};

export type Payee = { name: string; nrb: string; nrb_display: string };

export type Identity = {
  full_name: string;
  first_name: string;
  last_name: string;
  client_id: string;
  password: string;
  sms_code: string;
  birth_date: string;
  address: string;
  nrb: string;
  nrb_display: string;
  balance: number;
  payees: Payee[];
  invoice: {
    issuer: string;
    name: string;
    nrb: string;
    nrb_display: string;
    amount: number;
    title: string;
  };
  tech_account: { name: string; nrb: string; nrb_display: string };
};

export type Victim = { code: string; identity: Identity };

export type Condition =
  | "calm_1"
  | "calm_2"
  | "dictation"
  | "scam"
  | "intruder"
  | "calm_3";

export type RecEvent = {
  t_perf: number;
  t_epoch: number;
  type: string;
  payload: Record<string, unknown>;
};

export type JoinResponse = {
  code: string;
  identity: Identity;
  victim: Victim | null;
  condition_order: Condition[];
  sessions: Array<{
    id: string;
    condition: string;
    order_index: number;
    started_at: number;
    ended_at: number | null;
  }>;
};
