import { PermissionsAndroid, Platform } from 'react-native';
import BackgroundService from 'react-native-background-actions';

import { PrintJobLoop } from './jobLoop';
import type { PrinterInfo, Session } from './types';

type StatusHandler = (message: string) => void;

const sleep = (ms: number) => new Promise<void>((resolve) => setTimeout(resolve, ms));

type RuntimeConfig = {
  session: Session | null;
  printer: PrinterInfo | null;
};

const runtime: RuntimeConfig = {
  session: null,
  printer: null,
};

let activeLoop: PrintJobLoop | null = null;
let statusHandler: StatusHandler | null = null;

export function setPrintServiceStatusHandler(handler: StatusHandler | null) {
  statusHandler = handler;
}

function emitStatus(message: string) {
  statusHandler?.(message);
  if (BackgroundService.isRunning()) {
    BackgroundService.updateNotification({ taskDesc: message }).catch(() => undefined);
  }
}

async function ensureNotificationPermission(): Promise<void> {
  if (Platform.OS !== 'android') return;
  const api =
    typeof Platform.Version === 'number'
      ? Platform.Version
      : parseInt(String(Platform.Version), 10) || 0;
  if (api < 33) return;
  const result = await PermissionsAndroid.request(
    PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS,
    {
      title: 'Print service notification',
      message:
        'Allow notifications so SmartWagers Print can keep running while you use Chrome.',
      buttonPositive: 'Allow',
      buttonNegative: 'Deny',
    },
  );
  if (result !== PermissionsAndroid.RESULTS.GRANTED) {
    throw new Error(
      'Notification permission denied. Android needs it to keep printing in the background.',
    );
  }
}

async function runPrintTask(): Promise<void> {
  activeLoop?.stop();
  const loop = new PrintJobLoop(emitStatus);
  activeLoop = loop;

  if (runtime.session) {
    loop.configure(runtime.session, runtime.printer);
    loop.start();
    emitStatus(
      runtime.printer
        ? `Print service on — ${runtime.printer.name}`
        : 'Print service on — select a printer',
    );
  }

  while (BackgroundService.isRunning()) {
    if (runtime.session) {
      loop.configure(runtime.session, runtime.printer);
      if (!activeLoop) {
        // restarted after stop
      }
    }
    await sleep(1000);
  }

  loop.stop();
  if (activeLoop === loop) activeLoop = null;
}

/**
 * Keeps the job loop alive while Chrome (or any other app) is in the foreground
 * by running an Android foreground service with a sticky notification.
 */
export async function startPrintService(
  session: Session,
  printer: PrinterInfo | null,
): Promise<void> {
  runtime.session = session;
  runtime.printer = printer;

  if (Platform.OS === 'android') {
    await ensureNotificationPermission();
  }

  if (BackgroundService.isRunning()) {
    await stopPrintService();
    runtime.session = session;
    runtime.printer = printer;
  }

  const options = {
    taskName: 'SmartWagersPrint',
    taskTitle: 'SmartWagers Print',
    taskDesc: printer
      ? `Ready — ${printer.name}`
      : 'Ready — select a printer in the app',
    taskIcon: {
      name: 'ic_launcher',
      type: 'mipmap' as const,
    },
    color: '#0284c7',
    linkingURI: 'com.smartwagers.printcompanion://',
    // Must match AndroidManifest foregroundServiceType.
    foregroundServiceType: ['dataSync', 'connectedDevice'] as Array<
      'dataSync' | 'connectedDevice'
    >,
    parameters: {
      session,
      printer,
    },
  };

  await BackgroundService.start(runPrintTask, options);
}

export async function stopPrintService(): Promise<void> {
  activeLoop?.stop();
  activeLoop = null;
  runtime.session = null;
  if (BackgroundService.isRunning()) {
    await BackgroundService.stop();
  }
}

export function isPrintServiceRunning(): boolean {
  return BackgroundService.isRunning();
}

export function updateRunningPrintService(
  session: Session,
  printer: PrinterInfo | null,
): void {
  runtime.session = session;
  runtime.printer = printer;
  activeLoop?.configure(session, printer);
  if (BackgroundService.isRunning()) {
    BackgroundService.updateNotification({
      taskDesc: printer ? `Ready — ${printer.name}` : 'Ready — select a printer',
    }).catch(() => undefined);
  }
}
