import { requireNativeModule } from 'expo-modules-core';
import { Platform } from 'react-native';

export type UsbDeviceInfo = {
  deviceName: string;
  stableId: string;
  vendorId: number;
  productId: number;
  manufacturerName?: string;
  productName?: string;
  deviceClass?: number;
  interfaceCount?: number;
};

type UsbEscPosNative = {
  listDevices(): Promise<UsbDeviceInfo[]>;
  printRawBase64(deviceName: string, payloadBase64: string): Promise<void>;
};

function loadNative(): UsbEscPosNative | null {
  if (Platform.OS !== 'android') return null;
  try {
    return requireNativeModule('UsbEscPos') as UsbEscPosNative;
  } catch {
    return null;
  }
}

export function isUsbEscPosAvailable(): boolean {
  return loadNative() != null;
}

export async function listUsbDevices(): Promise<UsbDeviceInfo[]> {
  const native = loadNative();
  if (!native) return [];
  return native.listDevices();
}

export async function printUsbRawBase64(
  deviceName: string,
  payloadBase64: string,
): Promise<void> {
  const native = loadNative();
  if (!native) {
    throw new Error('USB ESC/POS module is not available on this platform.');
  }
  await native.printRawBase64(deviceName, payloadBase64);
}
