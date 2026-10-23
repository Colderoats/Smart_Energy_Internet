// TC04 - prosumers cannot edit blockchain records (EnergyMarket.sol).
// Run from blockchain/:  npx hardhat run ../tests/tc04_blockchain_immutability.js
// Uses the in-process Hardhat network; exits non-zero if any expectation fails.
const hre = require("hardhat");
const { ethers } = hre;

const results = [];
const check = (name, ok, detail = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  -> " + detail : ""}`);
};

async function snapshot(market, tradeId, seller, buyer) {
  const t = await market.getTrade(tradeId);
  const ev = (await market.queryFilter(market.filters.Settled(tradeId))).map((e) => ({
    txHash: e.transactionHash, block: e.blockNumber, args: e.args.map(String),
  }));
  return {
    trade: {
      seller: t.seller, buyer: t.buyer, priceMilli: String(t.priceMilli), matchedWh: String(t.matchedWh),
      meterSellerWh: String(t.meterSellerWh), meterBuyerWh: String(t.meterBuyerWh), metered: t.metered, settled: t.settled,
    },
    balances: { seller: String(await market.balanceMilli(seller)), buyer: String(await market.balanceMilli(buyer)) },
    tradeCount: String(await market.tradeCount()),
    settledEvents: ev,
  };
}

// returns the revert reason (custom error name / message) or null if the call succeeded
async function expectRevert(promise) {
  try {
    const tx = await promise;
    await tx.wait();
    return null;
  } catch (e) {
    return e.revertName || (e.message.match(/custom error '([^']+)'/) || [])[1] || e.shortMessage || e.message;
  }
}

async function main() {
  const [owner, gateway, seller, buyer] = await ethers.getSigners();
  const Market = await ethers.getContractFactory("EnergyMarket");
  const market = await Market.connect(owner).deploy(gateway.address);
  await market.waitForDeployment();

  await (await market.connect(seller).register(ethers.encodeBytes32String("seller_node"))).wait();
  await (await market.connect(buyer).register(ethers.encodeBytes32String("buyer_node"))).wait();
  await (await market.connect(seller).postOffer(5000, 120)).wait(); // 5 kWh at 120 milli/kWh
  await (await market.connect(buyer).postBid(4000, 150)).wait();    // 4 kWh at up to 150
  await (await market.connect(gateway).matchTrade(0, 0)).wait();
  await (await market.connect(gateway).submitMeter(0, 3800, 3900)).wait();
  const settleTx = await market.connect(seller).settle(0);
  const rc = await settleTx.wait();
  console.log(`Settlement tx ${rc.hash} block ${rc.blockNumber}`);

  const before = await snapshot(market, 0, seller.address, buyer.address);
  console.log("BEFORE:", JSON.stringify(before, null, 1));
  check("setup: trade settled with min(3800,3900)=3800 Wh at 120 => pay 456", before.trade.settled && before.balances.seller === "456" && before.balances.buyer === "-456");
  check("setup: Settlement event emitted once", before.settledEvents.length === 1 && before.settledEvents[0].txHash === rc.hash);

  const attempts = [];
  for (const [who, signer] of [["seller", seller], ["buyer", buyer]]) {
    const m = market.connect(signer);
    attempts.push([`(a) ${who} submitMeter overwrite`, () => m.submitMeter(0, 1, 1)]);
    attempts.push([`(a) ${who} submitMeter inflate`, () => m.submitMeter(0, 999999, 999999)]);
    attempts.push([`(b) ${who} settle again`, () => m.settle(0)]);
    attempts.push([`(c) ${who} matchTrade (create/alter trade)`, () => m.matchTrade(0, 0)]);
    attempts.push([`(c) ${who} advanceInterval`, () => m.advanceInterval()]);
    attempts.push([`(c) ${who} setGateway(self)`, () => m.setGateway(signer.address)]);
    attempts.push([`(c) ${who} re-register / change node id`, () => m.register(ethers.encodeBytes32String("hacked"))]);
  }
  // the gateway itself cannot re-meter or re-settle either (defence in depth, not asked but cheap)
  attempts.push(["extra: gateway submitMeter on settled trade", () => market.connect(gateway).submitMeter(0, 1, 1)]);

  for (const [label, fn] of attempts) {
    const reason = await expectRevert(fn());
    check(`${label} reverts`, reason !== null, reason || "DID NOT REVERT");
  }

  const after = await snapshot(market, 0, seller.address, buyer.address);
  check("trade data identical after attempts", JSON.stringify(before.trade) === JSON.stringify(after.trade));
  check("balances identical after attempts", JSON.stringify(before.balances) === JSON.stringify(after.balances));
  check("tradeCount unchanged", before.tradeCount === after.tradeCount);
  check("original Settlement event (tx hash, block, args) identical", JSON.stringify(before.settledEvents) === JSON.stringify(after.settledEvents));

  // (c) structural evidence: list every state-changing function in the ABI
  const writers = market.interface.fragments.filter((f) => f.type === "function" && !["view", "pure"].includes(f.stateMutability)).map((f) => f.name);
  console.log("State-changing functions in ABI:", writers.join(", "));
  const editors = writers.filter((n) => /^(set[A-Z]|edit|update|cancel|delete|modify|revoke)/.test(n) && n !== "setGateway");
  check("ABI has no edit/update/cancel/delete function for trade, price or quantity", editors.length === 0, `only owner-only setGateway matches; others: [${editors}]`);

  const failed = results.filter((r) => !r.ok);
  console.log(`\nTC04 ${failed.length ? "FAIL" : "PASS"}: ${results.length - failed.length}/${results.length} checks`);
  process.exitCode = failed.length ? 1 : 0;
}

main().catch((e) => { console.error(e); process.exit(2); });
