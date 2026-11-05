((config) => {
	if (window.__cmbOnePurchase) return false;
	let v;
	const root = document.querySelector("#app")?.__vue__;
	(function walk(x, d) {
		if (!x || d > 18) return;
		if (x.ordInfo && typeof x.preAmountExam === "function") v = x;
		(x.$children || []).forEach((y) => walk(y, d + 1));
	})(root, 0);
	const amountMatches = (value) =>
		Number(String(value).replace(/,/g, "")) === Number(config.amount);
	function matches() {
		return (
			v?.fndInn === config.code &&
			amountMatches(v.amount) &&
			v.viewType === "A" &&
			!document.hidden
		);
	}
	if (
		!matches() ||
		v.otherCardAccountUID ||
		v.isZzyAccount ||
		v.isNewProtocolCard
	)
		return false;
	const api = v.$apis;
	const originalBuy = v.doBuy,
		originalSubmit = api?.entrustBuy,
		other = api?.entrustOtherCardBuy;
	if ([originalBuy, originalSubmit, other].some((x) => typeof x !== "function"))
		return false;
	let credential = null,
		confirmed = false,
		buyCalls = 0,
		apiCalls = 0,
		blocked = 0,
		received = false,
		accepted = null,
		rejection = null;
	function deny() {
		blocked++;
		throw Error("purchase guard");
	}
	function buyGuard(pwd) {
		if (
			!confirmed ||
			buyCalls !== 0 ||
			!credential ||
			pwd !== credential ||
			!matches()
		)
			return deny();
		buyCalls++;
		return originalBuy.call(this, pwd);
	}
	function apiGuard(params, options) {
		if (
			!confirmed ||
			buyCalls !== 1 ||
			apiCalls !== 0 ||
			!credential ||
			!matches() ||
			params?.fndInn !== config.code ||
			!amountMatches(params.ordAmt) ||
			params.pwd !== credential
		)
			return deny();
		apiCalls++;
		credential = null;
		return Promise.resolve(
			originalSubmit.call(this, params, {
				...options,
				disableRetry: true,
				retryLimit: 0,
			}),
		).then((response) => {
			received = true;
			accepted = response?.code === 200;
			if (!accepted) {
				const message =
					typeof response?.message === "string" ? response.message : "";
				const code =
					message.match(/\b[A-Z][A-Z0-9]{4,11}(?=[-：:])/u)?.[0] ?? null;
				const category =
					[
						"国密加解密异常",
						"密码错误",
						"密码不正确",
						"额度不足",
						"系统繁忙",
						"交易失败",
						"会话失效",
						"超时",
					].find((word) => message.includes(word)) ?? null;
				rejection = { code, category };
			}
			return response;
		});
	}
	function intact() {
		return (
			v.doBuy === buyGuard &&
			api.entrustBuy === apiGuard &&
			api.entrustOtherCardBuy === deny
		);
	}
	try {
		v.doBuy = buyGuard;
		api.entrustBuy = apiGuard;
		api.entrustOtherCardBuy = deny;
		if (!intact()) throw Error("guard");
	} catch (_) {
		if (v.doBuy === buyGuard) v.doBuy = originalBuy;
		if (api.entrustBuy === apiGuard) api.entrustBuy = originalSubmit;
		if (api.entrustOtherCardBuy === deny) api.entrustOtherCardBuy = other;
		return false;
	}
	function getModal() {
		return v.$pwdModal?.Instance;
	}
	function validModal(m) {
		return (
			m?.value === true &&
			m.simulate === true &&
			m.autoSubmit === false &&
			m.encryptParam?.encType === "S" &&
			!m.encryptParam?.encFactor &&
			amountMatches(String(m.contentMoney).replace(/^[￥¥]\s*/, ""))
		);
	}
	function ready() {
		const m = getModal();
		return (
			!confirmed &&
			matches() &&
			intact() &&
			blocked === 0 &&
			validModal(m) &&
			!!credential &&
			m.simulateLen === 6 &&
			m.val === credential &&
			m.disabled === false
		);
	}
	window.__cmbOnePurchase = {
		stage(token, payload) {
			if (token !== config.token) return false;
			const m = getModal();
			if (
				confirmed ||
				credential ||
				blocked ||
				!matches() ||
				!intact() ||
				!validModal(m) ||
				payload?.length !== 6 ||
				typeof payload.text !== "string" ||
				!/^[a-f0-9]{200,260}$/i.test(payload.text)
			)
				return false;
			m.simulateInput(payload.text, payload.length);
			m.inputTextHash = payload.textHash;
			m.disabled = false;
			credential = payload.text;
			return ready();
		},
		meta(token) {
			if (token !== config.token) return null;
			const m = getModal();
			return {
				matches: matches(),
				intact: intact(),
				validModal: validModal(m),
				ready: ready(),
				confirmed,
				buyCalls,
				apiCalls,
				blocked,
				received,
				accepted,
				rejection,
			};
		},
		commit(token) {
			if (token !== config.token || config.dryRun || !ready()) return false;
			confirmed = true;
			getModal().onPwdModalConfirm();
			return true;
		},
		discard(token) {
			if (token !== config.token) return false;
			credential = null;
			if (confirmed) return true;
			const m = getModal();
			if (validModal(m)) m.onPwdModalClose();
			// Restore only if the modal was closed and the same wrappers are still present.
			if (m?.value) return false;
			if (intact()) {
				v.doBuy = originalBuy;
				api.entrustBuy = originalSubmit;
				api.entrustOtherCardBuy = other;
				delete window.__cmbOnePurchase;
			}
			return true;
		},
	};
	return true;
})(__CMB_PASSWORD_CONFIG__);
