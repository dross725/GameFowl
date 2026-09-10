import AsyncStorage from '@react-native-async-storage/async-storage';
import { Platform } from 'react-native';
import type { PlatformName, PrinterInfo, Session } from './types';

const SESSION_KEY = 'sw_print_session';
const PRINTER_KEY = 'sw_print_printer';

export async function loadSession(): Promise<Session | null> {
  const raw = await AsyncStorage.getItem(SESSION_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Session;
  } catch {
    return null;
  }
}

export async function saveSession(session: Session): Promise<void> {
  await AsyncStorage.setItem(SESSION_KEY, JSON.stringify(session));
}

export async function clearSession(): Promise<void> {
  await AsyncStorage.removeItem(SESSION_KEY);
}

export async function loadPrinter(): Promise<PrinterInfo | null> {
  const raw = await AsyncStorage.getItem(PRINTER_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as PrinterInfo;
  } catch {
    return null;
  }
}

export async function savePrinter(printer: PrinterInfo): Promise<void> {
  await AsyncStorage.setItem(PRINTER_KEY, JSON.stringify(printer));
}

export function currentPlatform(): PlatformName {
  return Platform.OS === 'ios' ? 'ios' : 'android';
}

export function normalizeServerUrl(url: string): string {
  let value = String(url || '').trim().replace(/\/$/, '');
  if (!value) return value;
  // Accept "192.168.1.6:8000" or "192.168.1.6" and force http for LAN servers.
  if (!/^https?:\/\//i.test(value)) {
    value = `http://${value}`;
  }
  // If user entered host only, assume Django dev port 8000.
  try {
    const parsed = new URL(value);
    if (!parsed.port && (parsed.hostname.startsWith('192.168.') || parsed.hostname.startsWith('10.') || parsed.hostname === 'localhost' || parsed.hostname === '127.0.0.1')) {
      parsed.port = '8000';
      value = parsed.toString().replace(/\/$/, '');
    }
  } catch {
    // leave as-is; login will surface a clear error
  }
  return value;
}

export function makeDeviceId(): string {
  return `dev-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}
