const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

const source = fs.readFileSync(
	path.join(__dirname, "../src/native_password_page.js"),
	"utf8",
);
const token = "fixture-token";
const code = "TEST01";
const text = "a".repeat(230);

function page(dryRun = false) {
	const requests = [];
	const modal = {
		value: true,
		simulate: true,
		autoSubmit: false,
		encryptParam: { encType: "S" },
		contentMoney: "￥1,234.56",
		disabled: true,
		simulateInput(value, length) {
			this.val = value;
			this.simulateLen = length;
		},
		onPwdModalConfirm() {
			return view.doBuy(this.val);
		},
		onPwdModalClose() {
			this.value = false;
			this.val = "";
		},
	};
	const view = {
		fndInn: code,
		amount: "1,234.56",
		viewType: "A",
		ordInfo: {},
		preAmountExam() {},
		$pwdModal: { Instance: modal },
		$apis: {
			entrustBuy(params, options) {
				requests.push({ params, options });
				return { code: 200 };
			},
			entrustOtherCardBuy() {
				throw new Error("unexpected card branch");
			},
		},
		doBuy(pwd) {
			return this.$apis.entrustBuy(
				{ fndInn: this.fndInn, ordAmt: this.amount, pwd },
				{},
			);
		},
	};
	const window = {};
	const document = { hidden: false, querySelector: () => ({ __vue__: view }) };
	assert.equal(
		vm.runInNewContext(
			source.replace(
				"__CMB_PASSWORD_CONFIG__",
				JSON.stringify({ code, amount: "1234.56", token, dryRun }),
			),
			{ window, document },
		),
		true,
	);
	return { view, modal, requests, guard: window.__cmbOnePurchase };
}

const payload = { length: 6, text, textHash: "" };

test("dry run stages the password but cannot confirm and clears the modal", () => {
	const { guard, requests, modal } = page(true);
	assert.equal(guard.stage(token, payload), true);
	assert.equal(guard.commit(token), false);
	assert.equal(guard.discard(token), true);
	assert.equal(modal.value, false);
	assert.equal(modal.val, "");
	assert.equal(requests.length, 0);
});

test("real confirmation admits one original API call with retries disabled", async () => {
	const { guard, requests } = page();
	assert.equal(guard.stage("stale-token", payload), false);
	assert.equal(guard.commit(token), false);
	assert.equal(guard.stage(token, payload), true);
	assert.equal(guard.commit(token), true);
	assert.equal(guard.commit(token), false);
	assert.equal(requests.length, 1);
	assert.equal(requests[0].options.disableRetry, true);
	assert.equal(requests[0].options.retryLimit, 0);
	await Promise.resolve();
	assert.equal(guard.meta(token).accepted, true);
});

test("a changed amount between staging and confirmation blocks purchase", () => {
	const { view, guard, requests } = page();
	assert.equal(guard.stage(token, payload), true);
	view.amount = "0.01";
	assert.equal(guard.commit(token), false);
	assert.equal(requests.length, 0);
});
