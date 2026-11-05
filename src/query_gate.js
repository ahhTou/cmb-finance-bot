/* Installed before any purchase-page script. Only wraps the page's queryBuy;
 * no HTTP replay, credentials, submission calls, or fabricated success data. */
(config => {
    'use strict';
    const state = window.__cmbQueryGate = {
        token: config.token, code: config.code, attempts: 0, heldCalls: 0,
        installed: false, status: 'installing', origin: performance.timeOrigin,
        reason: '', quota: null,
        // [attempt, round-trip ms, outcome] for every finished queryBuy: E = sold out.
        results: []
    };
    function record(ms, outcome) {
        state.results.push([state.attempts, Math.round(ms), outcome]);
    }
    const clockStart = performance.now();
    const wallStart = Date.now();
    const now = () => wallStart + performance.now() - clockStart;
    let lease = now() + config.leaseMs;
    let cancelled = false, resolved = false, flight = null;
    let badge;
    const names = {installing:'准备中', waiting:'等待开始', querying:'查询中',
        retrying:'等待重试', ready:'表单准备中', stopped:'已停止', complete:'已结束'};
    function countdown(milliseconds) {
        const seconds = Math.max(0, Math.ceil(milliseconds / 1000));
        const part = number => String(number).padStart(2, '0');
        const hours = Math.floor(seconds / 3600);
        const minutes = Math.floor(seconds / 60) % 60;
        const rest = `${part(minutes)}:${part(seconds % 60)}`;
        return hours ? `${part(hours)}:${rest}` : rest;
    }
    function render() {
        if (!document.documentElement) return;
        if (!badge) {
            badge = document.createElement('div');
            badge.id = 'cmb-query-status';
            Object.assign(badge.style, {
                position:'fixed', top:'calc(env(safe-area-inset-top, 0px) + 8px)',
                left:'50%', transform:'translateX(-50%)', width:'max-content',
                maxWidth:'calc(100vw - 24px)', zIndex:'2147483647',
                padding:'8px 14px', borderRadius:'16px', background:'rgba(0,0,0,.65)',
                color:'#fff', fontSize:'13px', lineHeight:'1.4',
                fontFamily:'-apple-system, sans-serif', pointerEvents:'none',
                backdropFilter:'blur(8px)', webkitBackdropFilter:'blur(8px)'
            });
        }
        if (!badge.isConnected) document.documentElement.appendChild(badge);
        const fields = [names[state.status] || state.status];
        const active = ['installing','waiting','querying','retrying'].includes(state.status);
        const current = now();
        if (active && current < config.startAt) {
            fields.push(`距开始 ${countdown(config.startAt - current)}`);
        } else if (active && config.mode === 'redemption') {
            fields.push(`剩余 ${countdown(config.endAt - current)}`);
        }
        fields.push(`已尝试 ${state.attempts} 次`);
        badge.textContent = fields.join(' · ');
    }
    function stop(reason) {
        cancelled = true; state.status = 'stopped'; state.reason = reason; render();
    }
    function check() {
        if (cancelled) throw Error(state.reason || 'query gate cancelled');
        if (now() > lease) { stop('watcher_lost'); throw Error('watcher lease expired'); }
    }
    // Redemption backoff: burst tier, linear ramp to the slow tier, then idle.
    function retryRange(elapsed) {
        const b = config.backoff;
        if (!b) return [config.retryMinMs, config.retryMaxMs];
        if (elapsed < b.burstMs) return b.burst;
        if (elapsed < b.rampMs) {
            const f = (elapsed - b.burstMs) / (b.rampMs - b.burstMs);
            return [0, 1].map(i => Math.round(b.burst[i] + f * (b.slow[i] - b.burst[i])));
        }
        if (elapsed < b.idleMs) return b.slow;
        return b.idle;
    }
    function sleep(ms) { return new Promise(resolve => setTimeout(resolve, ms)); }
    async function waitUntil(target) {
        while (now() < target) {
            check(); await sleep(Math.min(250, target - now()));
        }
        check();
    }
    state.keepAlive = token => {
        if (token !== config.token || cancelled) return false;
        lease = now() + config.leaseMs; return true;
    };
    state.cancel = token => { if (token === config.token) stop('cancelled'); };
    state.finish = token => {
        if (token === config.token) { state.status='complete'; render(); }
    };
    window.addEventListener('pagehide', () => stop('document_changed'), {once:true});
    document.addEventListener('visibilitychange', () => {if (document.hidden) stop('document_hidden');});
    const define = Object.defineProperty;
    let descriptorHook, descriptorsHook, reflectHook;
    const defines = Object.defineProperties;
    const reflectDefine = Reflect.defineProperty;
    function uninstallHook() {
        if (Object.defineProperty === descriptorHook) Object.defineProperty = define;
        if (Object.defineProperties === descriptorsHook) Object.defineProperties = defines;
        if (Reflect.defineProperty === reflectHook) Reflect.defineProperty = reflectDefine;
    }
    function install(api) {
        if (!api || typeof api.queryBuy !== 'function' || state.installed) return;
        const original = api.queryBuy;
        api.queryBuy = function(...args) {
            state.heldCalls++;
            const params = args[0];
            if (!params || String(params.fndInn) !== config.code) {
                stop('product_mismatch'); return Promise.reject(Error('queryBuy product mismatch'));
            }
            if (flight) return flight; // single flight, including after success
            flight = (async () => {
                state.status='waiting'; render();
                await waitUntil(config.startAt);
                while (true) {
                    check();
                    if (config.mode === 'redemption' && now() >= config.endAt) {
                        stop('window_expired'); throw Error('query window expired');
                    }
                    if (config.mode === 'first_launch' && state.attempts >= config.maxAttempts) {
                        stop('attempts_exhausted'); throw Error('query attempts exhausted');
                    }
                    state.attempts++; state.status='querying'; render();
                    let timer;
                    let response;
                    const sentAt = now();
                    try {
                        const remaining = config.mode === 'redemption'
                            ? Math.min(config.requestTimeoutMs, config.endAt - now())
                            : config.requestTimeoutMs;
                        response = await Promise.race([
                            Promise.resolve(original.apply(this,args)),
                            new Promise((_,reject) => {timer=setTimeout(() => reject(Error('query_timeout')),remaining);})
                        ]);
                    } catch (_) {
                        record(now() - sentAt, 'failed');
                        stop(config.mode === 'redemption' && now() >= config.endAt
                            ? 'window_expired' : 'query_failed');
                        throw Error('queryBuy failed or timed out');
                    } finally { clearTimeout(timer); }
                    const roundTrip = now() - sentAt;
                    check();
                    if (config.mode === 'redemption' && now() >= config.endAt) {
                        stop('window_expired'); throw Error('late query response');
                    }
                    const data = response && response.data;
                    // Match the page's own branching order. Unknown/server/login
                    // errors must never masquerade as sold-out responses.
                    const noQuota = response && response.code === 200 && data
                        && data.queryCode !== 'A' && data.hasAccount === true && data.ppsTag === 'E';
                    if (noQuota) {
                        record(roundTrip, 'E');
                        state.status='retrying'; render();
                        if (config.mode === 'redemption') {
                            const [min, max] = retryRange(now() - config.startAt);
                            const delay=min + Math.floor(Math.random()*(max-min+1));
                            await waitUntil(Math.min(config.endAt, now()+delay));
                        }
                        continue;
                    }
                    if (!response || response.code !== 200 || !data || data.queryCode === 'A'
                            || data.hasAccount !== true) {
                        record(roundTrip, 'rejected');
                        stop('query_rejected'); throw Error('queryBuy rejected; inspect bank page');
                    }
                    // Preserve the real response unchanged. The original page
                    // still handles risk/eligibility before rendering its form.
                    const quota = data.posQty;
                    state.quota = quota === undefined || quota === null || quota === ''
                        ? null : String(quota);
                    record(roundTrip, 'ready');
                    state.status='ready'; resolved=true; render();
                    // Wake the watcher now (CDP Runtime.addBinding); it still
                    // verifies everything itself, this only saves a poll.
                    try {
                        if (typeof window.__cmbGateReady === 'function') window.__cmbGateReady(config.token);
                    } catch (_) {}
                    return response;
                }
            })().catch(error => {
                // Expected automation stops must not enter the bank page's
                // generic "query failed" catch. Keep its consumer pending;
                // the stopped controller has no timers or requests left.
                const expected = ['cancelled','attempts_exhausted','window_expired',
                    'watcher_lost','document_changed','document_hidden'];
                if (expected.includes(state.reason)) return new Promise(() => {});
                throw error;
            });
            // The original page awaits this same promise; its failure branch
            // is left intact, and no rejection can trigger a second request.
            return flight;
        };
        state.installed = true; state.status='waiting'; uninstallHook(); render();
    }
    descriptorHook = function(target, key, descriptor) {
        if (key === '$apis') {
            const value = descriptor.get ? descriptor.get.call(target) : descriptor.value;
            install(value);
        }
        return define(target,key,descriptor);
    };
    descriptorsHook = function(target, descriptors) {
        if (descriptors.$apis) {
            const descriptor=descriptors.$apis;
            install(descriptor.get ? descriptor.get.call(target) : descriptor.value);
        }
        return defines(target,descriptors);
    };
    reflectHook = function(target,key,descriptor) {
        if (key === '$apis') install(descriptor.get ? descriptor.get.call(target) : descriptor.value);
        return reflectDefine(target,key,descriptor);
    };
    Object.defineProperty = descriptorHook;
    Object.defineProperties = descriptorsHook;
    Reflect.defineProperty = reflectHook;
    document.addEventListener('DOMContentLoaded',render,{once:true});
    const healthTimer=setInterval(() => {
        if (!resolved && !cancelled && now() > lease) stop('watcher_lost');
        if (cancelled) {uninstallHook();clearInterval(healthTimer);}
        render();
    },500);
})(__CONFIG__);
