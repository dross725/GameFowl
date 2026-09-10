export type PlatformName = 'android' | 'ios';

export type Session = {
  token: string;
  username: string;
  deviceId: string;
  platform: PlatformName;
  serverUrl: string;
};

export type PrinterInfo = {
  id: string;
  name: string;
  address: string;
  transport: 'classic' | 'ble';
};

export type PrintJobPayload = {
  id: number;
  endpoint: string;
  receipt_type?: string;
  transaction_id?: string;
  status: string;
  escpos_base64: string;
  payload?: Record<string, unknown>;
};
