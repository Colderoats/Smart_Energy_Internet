// Set-2 TC08 + TC09 (EnergyMarket.sol). Run from blockchain/:  npx hardhat run ../tests/tc_set2_market_events.js
// In-process Hardhat network; exits non-zero if any expectation fails.
//  TC08: register, offer, bid, match, meter, settle -> an event for each operation; gas per step reported.
//  TC09: offer (and bid) from an unregistered account -> transaction rejected, nothing stored.
const hre = require("hardhat");
const { ethers } = hre;

let failed = 0;
const check = (name, ok, detail = "") => {
  if (!ok) failed++;
  console.log(`${ok ? "PASS" : "FAIL"}  ${name}${detail ? "  -> " + detail : ""}`);
};
const events = (rc, c) => rc.logs.map((l) => { try { return c.interface.parseLog(l); } catch { return null; } }).filter(Boolean).map((p) => p.name);

async function main() {
  const [owner, gateway, seller, buyer, stranger] = await ethers.getSigners();
  const market = await (await ethers.getContractFactory("EnergyMarket")).connect(owner).deploy(gateway.address);
  await market.waitForDeployment();

  // ---- TC08 ----
  const steps = [
    ["register (seller)", () => market.connect(seller).register(ethers.encodeBytes32String("seller_node")), "Registered"],
    ["register (buyer)", () => market.connect(buyer).register(ethers.encodeBytes32String("buyer_node")), "Registered"],
    ["postOffer", () => market.connect(seller).postOffer(5000, 120), "OfferPosted"],
    ["postBid", () => market.connect(buyer).postBid(4000, 150), "BidPosted"],
    ["matchTrade", () => market.connect(gateway).matchTrade(0, 0), "TradeMatched"],
    ["submitMeter", () => market.connect(gateway).submitMeter(0, 3800, 3900), "Metered"],
    ["settle", () => market.connect(seller).settle(0), "Settled"],
  ];
  const gas = [];
  for (const [name, send, ev] of steps) {
    const rc = await (await send()).wait();
    const names = events(rc, market);
    gas.push([name, Number(rc.gasUsed)]);
    check(`TC08 ${name} emits ${ev}`, names.includes(ev), `gas ${rc.gasUsed}`);
  }
  const [top, topGas] = gas.reduce((a, b) => (b[1] > a[1] ? b : a));
  console.log(`TC08 highest gas: ${top} ${topGas}`);
  console.log("TC08 gas per step:", JSON.stringify(Object.fromEntries(gas)));
  const t = await market.getTrade(0);
  check("TC08 trade settled, balances +456/-456", t.settled && String(await market.balanceMilli(seller.address)) === "456" && String(await market.balanceMilli(buyer.address)) === "-456");

  // ---- TC09 ----
  const revertName = async (p) => {
    try { await (await p).wait(); return null; } catch (e) { return e.revertName || (e.message.match(/custom error '([^']+)'/) || [])[1] || e.shortMessage || e.message; }
  };
  const offers0 = await market.offerCount(), bids0 = await market.bidCount();
  const rOffer = await revertName(market.connect(stranger).postOffer(5000, 120));
  const rBid = await revertName(market.connect(stranger).postBid(5000, 150));
  check("TC09 offer from an unregistered account rejected", String(rOffer).startsWith("NotRegistered"), String(rOffer));
  check("TC09 bid from an unregistered account rejected", String(rBid).startsWith("NotRegistered"), String(rBid));
  check("TC09 no offer/bid stored, no event", (await market.offerCount()) === offers0 && (await market.bidCount()) === bids0);

  console.log(failed ? `\n${failed} FAILED` : "\nALL PASS");
  process.exit(failed ? 1 : 0);
}
main().catch((e) => { console.error(e); process.exit(1); });
