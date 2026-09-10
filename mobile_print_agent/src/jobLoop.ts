import { ackJob, decodeEscposBase64, fetchPendingJobs, wsPrintJobsUrl } from './api';
import { printRaw } from './bluetooth';
import type { PrinterInfo, PrintJobPayload, Session } from './types';

type StatusHandler = (message: string) => void;

export class PrintJobLoop {
  private session: Session | null = null;
  private printer: PrinterInfo | null = null;
  private timer: ReturnType<typeof setInterval> | null = null;
  private socket: WebSocket | null = null;
  private busy = false;
  private onStatus: StatusHandler;

  constructor(onStatus: StatusHandler) {
    this.onStatus = onStatus;
  }

  configure(session: Session, printer: PrinterInfo | null) {
    this.session = session;
    this.printer = printer;
  }

  start() {
    this.stop();
    if (!this.session) return;
    this.connectWs();
    this.timer = setInterval(() => {
      this.poll().catch(() => undefined);
    }, 1500);
    this.poll().catch(() => undefined);
  }

  stop() {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (this.socket) {
      try {
        this.socket.close();
      } catch {
        // ignore
      }
      this.socket = null;
    }
  }

  private connectWs() {
    if (!this.session) return;
    try {
      const url = wsPrintJobsUrl(this.session);
      const socket = new WebSocket(url);
      this.socket = socket;
      socket.onopen = () => this.onStatus('WebSocket connected');
      socket.onclose = () => this.onStatus('WebSocket closed — polling');
      socket.onerror = () => this.onStatus('WebSocket error — polling');
      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(String(event.data));
          if (data.type === 'print_job' || data.type === 'connected') {
            // Claim via HTTP so status transitions stay authoritative.
            this.poll().catch(() => undefined);
          }
        } catch {
          // ignore malformed
        }
      };
    } catch {
      this.onStatus('WebSocket unavailable — polling');
    }
  }

  private async poll() {
    if (!this.session || this.busy) return;
    const jobs = await fetchPendingJobs(this.session);
    for (const job of jobs) {
      await this.handleJob(job);
    }
  }

  private async handleJob(job: PrintJobPayload) {
    if (!this.session) return;
    if (this.busy) return;
    this.busy = true;
    try {
      if (!this.printer) {
        await ackJob(this.session, job.id, 'failed', 'No printer selected');
        this.onStatus(`Job #${job.id} failed: no printer selected`);
        return;
      }
      const bytes = decodeEscposBase64(job.escpos_base64);
      this.onStatus(`Printing job #${job.id} (${job.endpoint})…`);
      await printRaw(this.printer, bytes);
      await ackJob(this.session, job.id, 'printed');
      this.onStatus(`Printed job #${job.id}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      try {
        await ackJob(this.session, job.id, 'failed', message);
      } catch {
        // ignore ack failure
      }
      this.onStatus(`Job #${job.id} failed: ${message}`);
    } finally {
      this.busy = false;
    }
  }
}
