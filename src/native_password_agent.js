import Java from "frida-java-bridge";

const config = __CMB_PASSWORD_CONFIG__;
const sameAmount = (value) =>
	Number(String(value).replace(/,/g, "")) === Number(config.amount);
let service = null;
let targetWebView = null;
let requests = 0;
let initialSession = null;
const onMain = (fn) =>
	new Promise((resolve, reject) =>
		Java.perform(() =>
			Java.scheduleOnMainThread(() => {
				try {
					resolve(fn());
				} catch (_) {
					reject(new Error("native probe failed"));
				}
			}),
		),
	);
Java.perform(() => {
	const S = Java.use("cmb.pb.app.cmblfunc.CMBKeyboardOpenService");
	const Base = Java.use("com.pb.framework.cmblapi.e");
	const Entity = Java.use("com.pb.assemble.entity.a");
	const App = Java.use("cmb.pb.app.appstatus.CMBApplication");
	const Uri = Java.use("android.net.Uri");
	const postcardField = Base.class.getDeclaredField("mPostcard");
	postcardField.setAccessible(true);
	const open = S.callKeyBoard.overload();
	open.implementation = function () {
		requests++;
		try {
			const postcard = Java.cast(postcardField.get(this), Entity);
			const url = Uri.parse(postcard.j().getUrl());
			const matches =
				String(url.getHost()) === "mobile.cmbchina.com" &&
				String(url.getPath()).endsWith("/saentrustbuy.html") &&
				String(url.getQueryParameter("CodeInn")) === config.code &&
				String(url.getQueryParameter("FndInn")) === config.code &&
				sameAmount(url.getQueryParameter("CurDepositBuyAmount"));
			if (!matches || requests !== 1) {
				send({ stage: "rejected", requests });
				return;
			}
			service = Java.retain(this);
			targetWebView = Java.retain(postcard.j());
			const sid = App.getInstance().getSessionId();
			initialSession = sid === null ? null : String(sid);
			send({ stage: "captured", requests, sessionPresent: !!initialSession });
		} catch (_) {
			send({ stage: "capture_failed", requests });
		}
	};
	send({ stage: "ready" });
});
rpc.exports.check = () =>
	onMain(() => {
		if (!service || !targetWebView || requests !== 1 || !initialSession)
			throw new Error("unverified service");
		const S = Java.use("cmb.pb.app.cmblfunc.CMBKeyboardOpenService");
		const App = Java.use("cmb.pb.app.appstatus.CMBApplication");
		const State = Java.use("cmbkb.pb.cmbsafe.d");
		return {
			factorMode: S.v(service),
			packingMode: S.I(service),
			nativeState: State.a().e() === true,
			sessionUnchanged:
				String(App.getInstance().getSessionId()) === initialSession,
		};
	});
rpc.exports.stage = (paymentPassword) =>
	onMain(() => {
		if (
			!service ||
			!targetWebView ||
			requests !== 1 ||
			!initialSession ||
			!/^[0-9]{6}$/.test(paymentPassword)
		)
			throw new Error("unverified service or input");
		const S = Java.use("cmb.pb.app.cmblfunc.CMBKeyboardOpenService");
		const App = Java.use("cmb.pb.app.appstatus.CMBApplication");
		const Helper = Java.use("cmbkb.pb.util.b");
		const readInt = (name) => {
			const f = S.class.getDeclaredField(name);
			f.setAccessible(true);
			return f.getInt(service);
		};
		// These are distinct selectors. Using the factor mode for both selects a different SM2 key.
		const mode = S.v(service),
			packingMode = S.I(service),
			max = readInt("b");
		if (
			mode !== 1 ||
			packingMode !== 0 ||
			max !== 6 ||
			Java.use("cmbkb.pb.cmbsafe.d").a().e() !== true ||
			String(App.getInstance().getSessionId()) !== initialSession
		)
			throw new Error("configuration changed");
		const factor = service.c0(mode);
		if (factor === null || !String(factor).length)
			throw new Error("missing native context");
		const helper = Helper.$new(max, "", mode);
		try {
			for (let i = 0; i < max; i++) helper.t(i, paymentPassword[i]);
			paymentPassword = null;
			const output = String(helper.p(factor, packingMode));
			const count = helper.s();
			if (
				count !== 6 ||
				output.length < 200 ||
				output.length > 260 ||
				!/^[a-f0-9]+$/i.test(output)
			)
				throw new Error("unexpected output shape");
			const payload = JSON.parse(String(service.g0(output, count, helper.r())));
			if (
				payload.text !== output ||
				payload.length !== 6 ||
				String(App.getInstance().getSessionId()) !== initialSession
			)
				throw new Error("session or callback changed");
			targetWebView.evaluateJavascript(
				"window.__cmbOnePurchase?.stage(" +
					JSON.stringify(config.token) +
					"," +
					JSON.stringify(payload) +
					")",
				null,
			);
			return {
				requests,
				mode,
				packingMode,
				inputLength: count,
				outputLength: output.length,
			};
		} finally {
			paymentPassword = null;
			try {
				helper.m();
			} catch (_) {}
			service.$dispose();
			service = null;
			targetWebView.$dispose();
			targetWebView = null;
			initialSession = null;
		}
	});
