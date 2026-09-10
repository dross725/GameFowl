/**
 * SmartWagers print router: Windows localhost agent when healthy, else server queue
 * for mobile Bluetooth companion apps.
 */
(function (global) {
    "use strict";

    const DEFAULT_LOCAL_URL = "http://127.0.0.1:8765";
    const HEALTH_TIMEOUT_MS = 800;
    const LOCAL_PRINT_TIMEOUT_MS = 30000;
    const SERVER_PRINT_TIMEOUT_MS = 15000;
    const MODE_KEY = "smartwagersPrintMode"; // local | server | auto

    let healthCache = { at: 0, ok: false };

    function getLocalPrintAgentUrl() {
        return (localStorage.getItem("smartwagersPrintAgentUrl") || DEFAULT_LOCAL_URL).replace(/\/$/, "");
    }

    function getPrintMode() {
        const mode = String(localStorage.getItem(MODE_KEY) || "auto").toLowerCase();
        if (mode === "local" || mode === "server") return mode;
        return "auto";
    }

    function getCsrfToken() {
        const input = document.querySelector("[name=csrfmiddlewaretoken]");
        if (input && input.value) return input.value;
        const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
        return match ? decodeURIComponent(match[1]) : "";
    }

    function isLikelyMobile() {
        return /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent || "");
    }

    async function probeLocalAgent(force) {
        const now = Date.now();
        if (!force && now - healthCache.at < 5000) {
            return healthCache.ok;
        }
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
        try {
            const response = await fetch(`${getLocalPrintAgentUrl()}/health`, {
                method: "GET",
                signal: controller.signal,
                cache: "no-store",
            });
            healthCache = { at: Date.now(), ok: response.ok };
            return healthCache.ok;
        } catch (error) {
            healthCache = { at: Date.now(), ok: false };
            return false;
        } finally {
            clearTimeout(timeoutId);
        }
    }

    async function shouldUseLocalAgent() {
        const mode = getPrintMode();
        if (mode === "local") return true;
        if (mode === "server") return false;
        if (isLikelyMobile()) {
            // Still probe in case a tablet shares a Windows agent somehow.
            return probeLocalAgent(false);
        }
        return probeLocalAgent(false);
    }

    async function postLocal(path, receipt, options) {
        const keepalive = Boolean(options && options.keepalive);
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), LOCAL_PRINT_TIMEOUT_MS);
        try {
            const response = await fetch(`${getLocalPrintAgentUrl()}${path}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(receipt),
                signal: controller.signal,
                keepalive: keepalive,
            });
            let result = {};
            try {
                result = await response.json();
            } catch (error) {
                result = {};
            }
            if (!response.ok || !result.ok) {
                return {
                    ok: false,
                    message: result.error || `Local print agent returned HTTP ${response.status}.`,
                    via: "local",
                };
            }
            return {
                ok: true,
                message: result.message || "Receipt sent to local printer.",
                via: "local",
            };
        } catch (error) {
            return {
                ok: false,
                message: error.name === "AbortError"
                    ? "Local print agent did not respond in time."
                    : "Local print agent is not running or is blocked.",
                via: "local",
            };
        } finally {
            clearTimeout(timeoutId);
        }
    }

    async function postServerQueue(endpoint, receipt) {
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), SERVER_PRINT_TIMEOUT_MS);
        const csrf = getCsrfToken();
        try {
            const response = await fetch("/api/print-jobs/", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                    "X-Requested-With": "XMLHttpRequest",
                    ...(csrf ? { "X-CSRFToken": csrf } : {}),
                },
                body: JSON.stringify({ endpoint: endpoint, receipt: receipt }),
                signal: controller.signal,
                credentials: "same-origin",
            });
            let result = {};
            try {
                result = await response.json();
            } catch (error) {
                result = {};
            }
            if (!response.ok || !result.ok) {
                return {
                    ok: false,
                    message: result.error || `Print queue returned HTTP ${response.status}.`,
                    via: "server",
                };
            }
            return {
                ok: true,
                message: result.message || "Receipt queued for mobile print companion.",
                job_id: result.job_id,
                via: "server",
            };
        } catch (error) {
            return {
                ok: false,
                message: error.name === "AbortError"
                    ? "Print queue did not respond in time."
                    : "Unable to reach the print queue. Is the companion app online?",
                via: "server",
            };
        } finally {
            clearTimeout(timeoutId);
        }
    }

    async function deliver(endpoint, path, receipt, options) {
        if (!receipt) {
            return { ok: false, message: "Missing receipt payload." };
        }
        const useLocal = await shouldUseLocalAgent();
        if (useLocal) {
            const localResult = await postLocal(path, receipt, options);
            if (localResult.ok) return localResult;
            // Fall back to server queue when local fails (mobile / missing agent).
            if (getPrintMode() === "local") return localResult;
            return postServerQueue(endpoint, receipt);
        }
        return postServerQueue(endpoint, receipt);
    }

    async function printWagerReceipt(receipt, options) {
        return deliver("wager", "/print-wager", receipt, options);
    }

    async function printPayoutReceipt(data) {
        const receipt = data && data.receipt ? data.receipt : data;
        return deliver("payout", "/print-payout", receipt, null);
    }

    async function printRemitReceipt(receipt) {
        return deliver("remit", "/print-remit", receipt, null);
    }

    const api = {
        getLocalPrintAgentUrl,
        getPrintMode,
        probeLocalAgent,
        printWagerReceipt,
        printPayoutReceipt,
        printRemitReceipt,
        deliver,
    };

    global.SmartWagersPrint = api;
    global.getLocalPrintAgentUrl = getLocalPrintAgentUrl;
    global.printWagerReceipt = printWagerReceipt;
    global.printPayoutReceipt = printPayoutReceipt;
    global.printRemitReceipt = printRemitReceipt;
})(typeof window !== "undefined" ? window : this);
