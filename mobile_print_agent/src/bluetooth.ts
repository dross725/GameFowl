import { Buffer } from 'buffer';
import { PermissionsAndroid, Platform } from 'react-native';
import type { Device } from 'react-native-ble-plx';
import type { PrinterInfo } from './types';

/**
 * Bluetooth print transport.
 * - Android: Classic Bluetooth SPP (RFCOMM) via react-native-bluetooth-classic
 * - iOS: BLE GATT via react-native-ble-plx (Classic SPP is not available on iOS)
 *
 * Native modules are loaded lazily so importing this file does not initialize
 * platform-incompatible Bluetooth stacks at module load time.
 */

const BLE_SERVICE_HINTS = [
  '18f0', // common ESC/POS BLE service
  'ffe0',
  'ff00',
  '49535343-fe7d-4ae5-8fa9-9fafd205e455',
];

type ClassicModule = typeof import('react-native-bluetooth-classic').default;
type BleModule = typeof import('react-native-ble-plx');

function loadClassic(): ClassicModule {
  // Native Classic SPP is Android-only for our use case.
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('react-native-bluetooth-classic').default as ClassicModule;
}

function loadBle(): BleModule {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return require('react-native-ble-plx') as BleModule;
}

function toBase64(bytes: Uint8Array): string {
  return Buffer.from(bytes).toString('base64');
}

function chunkBytes(bytes: Uint8Array, size: number): Uint8Array[] {
  const chunks: Uint8Array[] = [];
  for (let i = 0; i < bytes.length; i += size) {
    chunks.push(bytes.subarray(i, i + size));
  }
  return chunks;
}

function androidApiLevel(): number {
  return typeof Platform.Version === 'number'
    ? Platform.Version
    : parseInt(String(Platform.Version), 10) || 0;
}

/**
 * Android 12+ requires runtime BLUETOOTH_CONNECT / BLUETOOTH_SCAN.
 * Calling bonded-device APIs without them crashes the activity (looks like the app "minimized").
 */
export async function ensureBluetoothPermissions(): Promise<void> {
  if (Platform.OS !== 'android') return;

  if (androidApiLevel() >= 31) {
    const result = await PermissionsAndroid.requestMultiple([
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT,
      PermissionsAndroid.PERMISSIONS.BLUETOOTH_SCAN,
    ]);
    const connect =
      result[PermissionsAndroid.PERMISSIONS.BLUETOOTH_CONNECT] ===
      PermissionsAndroid.RESULTS.GRANTED;
    if (!connect) {
      throw new Error(
        'Bluetooth permission denied. Open App Settings → Permissions → allow Nearby devices / Bluetooth, then try again.',
      );
    }
    return;
  }

  // Android 11 and below: listing BT devices historically required location.
  const fine = await PermissionsAndroid.request(
    PermissionsAndroid.PERMISSIONS.ACCESS_FINE_LOCATION,
    {
      title: 'Bluetooth access',
      message:
        'Location permission is required on this Android version to list paired Bluetooth printers.',
      buttonPositive: 'Allow',
      buttonNegative: 'Deny',
    },
  );
  if (fine !== PermissionsAndroid.RESULTS.GRANTED) {
    throw new Error(
      'Location permission denied. It is required for Bluetooth on Android 11 and below.',
    );
  }
}

async function listClassicPrinters(): Promise<PrinterInfo[]> {
  await ensureBluetoothPermissions();
  const RNBluetoothClassic = loadClassic();

  const available = await RNBluetoothClassic.isBluetoothAvailable();
  if (!available) {
    throw new Error('This device has no Bluetooth adapter.');
  }

  const enabled = await RNBluetoothClassic.isBluetoothEnabled();
  if (!enabled) {
    // System enable dialog is OK after permissions; avoid calling it without them.
    const turnedOn = await RNBluetoothClassic.requestBluetoothEnabled();
    if (!turnedOn) {
      throw new Error('Bluetooth is off. Turn it on, then tap Scan printers again.');
    }
  }

  const bonded = await RNBluetoothClassic.getBondedDevices();
  return (bonded || []).map((device) => ({
    id: String(device.id || device.address || ''),
    name: String(device.name || device.address || 'Bluetooth Printer'),
    address: String(device.address || device.id || ''),
    transport: 'classic' as const,
  }));
}

async function printClassic(printer: PrinterInfo, bytes: Uint8Array): Promise<void> {
  await ensureBluetoothPermissions();
  const RNBluetoothClassic = loadClassic();
  const address = printer.address || printer.id;
  const connected = await RNBluetoothClassic.isDeviceConnected(address);
  if (!connected) {
    await RNBluetoothClassic.connectToDevice(address);
  }
  // Pass a Buffer so the library base64-encodes raw ESC/POS once for the bridge.
  await RNBluetoothClassic.writeToDevice(address, Buffer.from(bytes));
}

async function waitForBlePoweredOn(
  manager: InstanceType<BleModule['BleManager']>,
  State: BleModule['State'],
): Promise<void> {
  const state = await manager.state();
  if (state === State.PoweredOn) return;

  await new Promise<void>((resolve, reject) => {
    const sub = manager.onStateChange((next) => {
      if (next === State.PoweredOn) {
        sub.remove();
        resolve();
      }
    }, true);
    setTimeout(() => {
      sub.remove();
      reject(new Error('Bluetooth is not powered on'));
    }, 8000);
  });
}

async function listBlePrinters(): Promise<PrinterInfo[]> {
  const { BleManager, State } = loadBle();
  const manager = new BleManager();
  try {
    await waitForBlePoweredOn(manager, State);

    const found = new Map<string, PrinterInfo>();
    await new Promise<void>((resolve) => {
      manager.startDeviceScan(null, null, (error: Error | null, device: Device | null) => {
        if (error) {
          manager.stopDeviceScan();
          resolve();
          return;
        }
        if (!device) return;
        const name = String(device.name || device.localName || '');
        if (!name) return;
        const looksPrinter = /print|pos|rpp|xp-|thermal|receipt/i.test(name);
        if (!looksPrinter) return;
        found.set(device.id, {
          id: device.id,
          name,
          address: device.id,
          transport: 'ble',
        });
      });
      setTimeout(() => {
        manager.stopDeviceScan();
        resolve();
      }, 6000);
    });
    return Array.from(found.values());
  } finally {
    manager.destroy();
  }
}

async function printBle(printer: PrinterInfo, bytes: Uint8Array): Promise<void> {
  const { BleManager } = loadBle();
  const manager = new BleManager();
  try {
    const device = await manager.connectToDevice(printer.address || printer.id, {
      timeout: 10000,
    });
    await device.discoverAllServicesAndCharacteristics();
    const services = await device.services();
    let writeService: string | null = null;
    let writeChar: string | null = null;
    let withoutResponse = false;

    for (const service of services) {
      const chars = await device.characteristicsForService(service.uuid);
      for (const characteristic of chars) {
        const uuid = String(characteristic.uuid || '').toLowerCase();
        const serviceUuid = String(service.uuid || '').toLowerCase();
        const canWrite =
          characteristic.isWritableWithResponse || characteristic.isWritableWithoutResponse;
        if (!canWrite) continue;
        const preferred =
          BLE_SERVICE_HINTS.some((hint) => serviceUuid.includes(hint) || uuid.includes(hint)) ||
          !writeChar;
        if (preferred) {
          writeService = service.uuid;
          writeChar = characteristic.uuid;
          withoutResponse = Boolean(characteristic.isWritableWithoutResponse);
          if (BLE_SERVICE_HINTS.some((hint) => serviceUuid.includes(hint) || uuid.includes(hint))) {
            break;
          }
        }
      }
      if (
        writeService &&
        writeChar &&
        BLE_SERVICE_HINTS.some((hint) => String(writeService).toLowerCase().includes(hint))
      ) {
        break;
      }
    }

    if (!writeService || !writeChar) {
      throw new Error(
        'No writable BLE characteristic found. Use a dual-mode / iOS-compatible ESC/POS printer.',
      );
    }

    for (const part of chunkBytes(bytes, 180)) {
      const payload = toBase64(part);
      if (withoutResponse) {
        await device.writeCharacteristicWithoutResponseForService(
          writeService,
          writeChar,
          payload,
        );
      } else {
        await device.writeCharacteristicWithResponseForService(
          writeService,
          writeChar,
          payload,
        );
      }
    }
    await device.cancelConnection();
  } finally {
    manager.destroy();
  }
}

export async function listPrinters(): Promise<PrinterInfo[]> {
  if (Platform.OS === 'ios') {
    return listBlePrinters();
  }
  return listClassicPrinters();
}

export async function printRaw(printer: PrinterInfo, bytes: Uint8Array): Promise<void> {
  if (Platform.OS === 'ios' || printer.transport === 'ble') {
    await printBle(printer, bytes);
    return;
  }
  await printClassic(printer, bytes);
}

export function platformPrintHint(): string {
  if (Platform.OS === 'ios') {
    return (
      'iOS requires a BLE or dual-mode ESC/POS printer. ' +
      'Classic Bluetooth (SPP-only) printers are not supported by Apple.'
    );
  }
  return (
    'Android uses Classic Bluetooth SPP. Pair the printer in Android Settings first, ' +
    'allow Bluetooth / Nearby devices when prompted, then Scan.'
  );
}
