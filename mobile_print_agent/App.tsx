import Constants from 'expo-constants';
import { activateKeepAwakeAsync, deactivateKeepAwake } from 'expo-keep-awake';
import { StatusBar } from 'expo-status-bar';
import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  Platform,
  SafeAreaView,
  StyleSheet,
  Text,
  TextInput,
  TouchableOpacity,
  View,
} from 'react-native';

import { buildTestEscposBytes, healthCheck, loginCompanion, registerPrinter } from './src/api';
import { listPrinters, platformPrintHint, printRaw } from './src/bluetooth';
import { PrintJobLoop } from './src/jobLoop';
import {
  setPrintServiceStatusHandler,
  startPrintService,
  stopPrintService,
  updateRunningPrintService,
} from './src/printService';
import {
  clearSession,
  currentPlatform,
  loadPrinter,
  loadSession,
  makeDeviceId,
  normalizeServerUrl,
  savePrinter,
  saveSession,
} from './src/storage';
import type { PrinterInfo, Session } from './src/types';

const APP_VERSION = Constants.expoConfig?.version || '1.0.4';

export default function App() {
  const [booting, setBooting] = useState(true);
  const [session, setSession] = useState<Session | null>(null);
  const [printer, setPrinter] = useState<PrinterInfo | null>(null);
  const [serverUrl, setServerUrl] = useState('http://192.168.1.6:8000');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [status, setStatus] = useState('Ready');
  const [busy, setBusy] = useState(false);
  const [serviceOn, setServiceOn] = useState(false);
  const [printers, setPrinters] = useState<PrinterInfo[]>([]);
  const loopRef = useRef<PrintJobLoop | null>(null);

  const hint = useMemo(() => platformPrintHint(), []);

  useEffect(() => {
    (async () => {
      const savedSession = await loadSession();
      const savedPrinter = await loadPrinter();
      if (savedSession) {
        setSession(savedSession);
        setServerUrl(savedSession.serverUrl);
        setUsername(savedSession.username);
      }
      if (savedPrinter) setPrinter(savedPrinter);
      setBooting(false);
    })().catch(() => setBooting(false));
  }, []);

  useEffect(() => {
    setPrintServiceStatusHandler(setStatus);
    const loop = new PrintJobLoop(setStatus);
    loopRef.current = loop;
    return () => {
      setPrintServiceStatusHandler(null);
      loop.stop();
      stopPrintService().catch(() => undefined);
    };
  }, []);

  useEffect(() => {
    if (!session || !serviceOn) {
      loopRef.current?.stop();
      deactivateKeepAwake();
      stopPrintService().catch(() => undefined);
      return;
    }

    let cancelled = false;

    (async () => {
      try {
        if (Platform.OS === 'android') {
          // Foreground service keeps polling/printing while Chrome is on top.
          await startPrintService(session, printer);
          if (!cancelled) {
            setStatus(
              printer
                ? `Service ON — use Chrome freely (${printer.name})`
                : 'Service ON — select a printer first',
            );
          }
        } else {
          // iOS background is limited; keep awake while companion stays visible.
          loopRef.current?.configure(session, printer);
          loopRef.current?.start();
          await activateKeepAwakeAsync('print-service');
        }
      } catch (error) {
        if (!cancelled) {
          setServiceOn(false);
          setStatus(error instanceof Error ? error.message : String(error));
        }
      }
    })();

    return () => {
      cancelled = true;
      loopRef.current?.stop();
      deactivateKeepAwake();
      stopPrintService().catch(() => undefined);
    };
  }, [session, serviceOn]);

  useEffect(() => {
    if (!session || !serviceOn) return;
    if (Platform.OS === 'android') {
      updateRunningPrintService(session, printer);
    } else {
      loopRef.current?.configure(session, printer);
    }
  }, [session, printer, serviceOn]);

  async function onLogin() {
    setBusy(true);
    try {
      const normalized = normalizeServerUrl(serverUrl);
      const deviceId = session?.deviceId || makeDeviceId();
      const result = await loginCompanion({
        serverUrl: normalized,
        username: username.trim(),
        password,
        deviceId,
        platform: currentPlatform(),
        printerName: printer?.name,
        printerAddress: printer?.address,
      });
      const next: Session = {
        token: result.token,
        username: result.user,
        deviceId,
        platform: currentPlatform(),
        serverUrl: normalized,
      };
      await saveSession(next);
      setSession(next);
      setPassword('');
      setStatus(`Logged in as ${result.user}`);
      setServiceOn(true);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function onLogout() {
    setServiceOn(false);
    await stopPrintService().catch(() => undefined);
    await clearSession();
    setSession(null);
    setStatus('Logged out');
  }

  async function onScanPrinters() {
    setBusy(true);
    setStatus('Scanning printers…');
    try {
      const found = await listPrinters();
      setPrinters(found);
      setStatus(found.length ? `Found ${found.length} printer(s)` : 'No printers found');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function onSelectPrinter(item: PrinterInfo) {
    setPrinter(item);
    await savePrinter(item);
    if (session) {
      try {
        await registerPrinter(session, item.name, item.address);
      } catch {
        // pairing metadata is best-effort
      }
      if (serviceOn && Platform.OS === 'android') {
        updateRunningPrintService(session, item);
      }
    }
    setStatus(`Selected ${item.name}`);
  }

  async function onTestPrint() {
    if (!printer) {
      setStatus('Select a printer first');
      return;
    }
    setBusy(true);
    try {
      await printRaw(printer, buildTestEscposBytes());
      setStatus('Test print sent');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  async function onHealth() {
    if (!session) return;
    setBusy(true);
    try {
      const health = await healthCheck(session);
      setStatus(`Server OK — ${health.pending_jobs} pending job(s)`);
    } catch (error) {
      setStatus(error instanceof Error ? error.message : String(error));
    } finally {
      setBusy(false);
    }
  }

  if (booting) {
    return (
      <SafeAreaView style={styles.safe}>
        <ActivityIndicator color="#38bdf8" />
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="light" />
      <View style={styles.header}>
        <Text style={styles.brand}>SmartWagers Print</Text>
        <Text style={styles.sub}>
          Bluetooth companion · {currentPlatform()} · v{APP_VERSION}
        </Text>
      </View>

      <Text style={styles.hint}>{hint}</Text>

      {!session ? (
        <View style={styles.card}>
          <Text style={styles.label}>Server URL</Text>
          <TextInput
            style={styles.input}
            autoCapitalize="none"
            autoCorrect={false}
            value={serverUrl}
            onChangeText={setServerUrl}
            placeholder="http://192.168.1.6:8000"
            placeholderTextColor="#64748b"
          />
          <Text style={styles.label}>Username</Text>
          <TextInput
            style={styles.input}
            autoCapitalize="none"
            value={username}
            onChangeText={setUsername}
            placeholderTextColor="#64748b"
          />
          <Text style={styles.label}>Password</Text>
          <TextInput
            style={styles.input}
            secureTextEntry
            value={password}
            onChangeText={setPassword}
            placeholderTextColor="#64748b"
          />
          <TouchableOpacity style={styles.button} onPress={onLogin} disabled={busy}>
            <Text style={styles.buttonText}>{busy ? 'Signing in…' : 'Sign in'}</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <View style={styles.card}>
          <Text style={styles.label}>Signed in as {session.username}</Text>
          <Text style={styles.meta}>{session.serverUrl}</Text>
          <Text style={styles.meta}>
            Printer: {printer ? `${printer.name} (${printer.transport})` : 'none selected'}
          </Text>
          <Text style={styles.meta}>
            Service:{' '}
            {serviceOn
              ? Platform.OS === 'android'
                ? 'ON — keep notification; use Chrome to bet'
                : 'ON — leave this screen open while betting'
              : 'OFF'}
          </Text>
          <View style={styles.row}>
            <TouchableOpacity
              style={[styles.button, styles.half]}
              onPress={() => setServiceOn((v) => !v)}
            >
              <Text style={styles.buttonText}>{serviceOn ? 'Stop service' : 'Start service'}</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.button, styles.half, styles.ghost]} onPress={onLogout}>
              <Text style={styles.buttonText}>Log out</Text>
            </TouchableOpacity>
          </View>
          <View style={styles.row}>
            <TouchableOpacity style={[styles.button, styles.half]} onPress={onScanPrinters} disabled={busy}>
              <Text style={styles.buttonText}>Scan printers</Text>
            </TouchableOpacity>
            <TouchableOpacity style={[styles.button, styles.half]} onPress={onTestPrint} disabled={busy}>
              <Text style={styles.buttonText}>Test print</Text>
            </TouchableOpacity>
          </View>
          <TouchableOpacity style={[styles.button, styles.ghost]} onPress={onHealth} disabled={busy}>
            <Text style={styles.buttonText}>Check server</Text>
          </TouchableOpacity>
        </View>
      )}

      <FlatList
        data={printers}
        keyExtractor={(item) => item.id}
        style={styles.list}
        ListHeaderComponent={printers.length ? <Text style={styles.label}>Nearby / bonded</Text> : null}
        renderItem={({ item }) => (
          <TouchableOpacity style={styles.printerRow} onPress={() => onSelectPrinter(item)}>
            <Text style={styles.printerName}>{item.name}</Text>
            <Text style={styles.meta}>
              {item.transport} · {item.address}
            </Text>
          </TouchableOpacity>
        )}
      />

      <Text style={styles.status}>{status}</Text>
    </SafeAreaView>
  );
}

const styles = StyleSheet.create({
  safe: {
    flex: 1,
    backgroundColor: '#0f172a',
    paddingHorizontal: 16,
    paddingTop: 12,
  },
  header: {
    marginBottom: 12,
  },
  brand: {
    color: '#f8fafc',
    fontSize: 28,
    fontWeight: '700',
  },
  sub: {
    color: '#94a3b8',
    marginTop: 4,
  },
  hint: {
    color: '#fbbf24',
    marginBottom: 12,
    lineHeight: 20,
  },
  card: {
    backgroundColor: '#1e293b',
    borderRadius: 12,
    padding: 14,
    marginBottom: 12,
  },
  label: {
    color: '#e2e8f0',
    marginBottom: 6,
    fontWeight: '600',
  },
  meta: {
    color: '#94a3b8',
    marginBottom: 4,
  },
  input: {
    backgroundColor: '#0f172a',
    color: '#f8fafc',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#334155',
  },
  button: {
    backgroundColor: '#0284c7',
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
    marginTop: 6,
  },
  ghost: {
    backgroundColor: '#334155',
  },
  buttonText: {
    color: '#f8fafc',
    fontWeight: '700',
  },
  row: {
    flexDirection: 'row',
    gap: 8,
  },
  half: {
    flex: 1,
  },
  list: {
    flexGrow: 0,
    maxHeight: 220,
  },
  printerRow: {
    backgroundColor: '#1e293b',
    borderRadius: 8,
    padding: 12,
    marginBottom: 8,
  },
  printerName: {
    color: '#f8fafc',
    fontWeight: '600',
  },
  status: {
    color: '#7dd3fc',
    marginTop: 8,
    marginBottom: 16,
  },
});
