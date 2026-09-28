const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");
const { anyValue } = require("@nomicfoundation/hardhat-chai-matchers/withArgs");

const EventType = { ENERGY_REDISTRIBUTION: 0, P2P_TRADE: 1, FAULT_ALERT: 2, FL_ROUND: 3 };

// Same canonical form the backend uses (backend/app/blockchain/hashing.py):
// keys sorted recursively, no whitespace, UTF-8.
function canonical(value) {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (value && typeof value === "object") {
    const parts = Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`);
    return `{${parts.join(",")}}`;
  }
  return JSON.stringify(value);
}
const fingerprint = (payload) => ethers.keccak256(ethers.toUtf8Bytes(canonical(payload)));

const tradePayload = {
  event_type: "P2P_TRADE",
  provenance: "simulated",
  seller: "wind_scada_kelmarsh_1",
  buyer: "hydro_01",
  kwh: 12.5,
  price_per_kwh: 0.11,
};

async function deployFixture() {
  const [owner, stranger] = await ethers.getSigners();
  const ledger = await (await ethers.getContractFactory("EnergyLedger")).deploy();
  return { ledger, owner, stranger };
}

describe("EnergyLedger", function () {
  describe("happy path", function () {
    it("starts empty and records the deployer as owner", async function () {
      const { ledger, owner } = await loadFixture(deployFixture);
      expect(await ledger.recordCount()).to.equal(0n);
      expect(await ledger.owner()).to.equal(owner.address);
    });

    it("appends records with sequential ids and stores every field", async function () {
      const { ledger, owner } = await loadFixture(deployFixture);
      const h1 = fingerprint(tradePayload);
      const h2 = fingerprint({ event_type: "FAULT_ALERT", node_id: "wind_scada_kelmarsh_2" });
      await ledger.appendRecord(EventType.P2P_TRADE, h1, "wind_scada_kelmarsh_1");
      await ledger.appendRecord(EventType.FAULT_ALERT, h2, "wind_scada_kelmarsh_2");

      expect(await ledger.recordCount()).to.equal(2n);
      const r0 = await ledger.getRecord(0);
      expect(r0.id).to.equal(0n);
      expect(r0.eventType).to.equal(BigInt(EventType.P2P_TRADE));
      expect(r0.payloadHash).to.equal(h1);
      expect(r0.actor).to.equal("wind_scada_kelmarsh_1");
      expect(r0.recorder).to.equal(owner.address);
      expect(r0.timestamp).to.be.greaterThan(0n);
      const r1 = await ledger.getRecord(1);
      expect(r1.id).to.equal(1n);
      expect(r1.eventType).to.equal(BigInt(EventType.FAULT_ALERT));
      expect(r1.payloadHash).to.equal(h2);
    });
  });

  describe("append-only guarantee", function () {
    it("exposes no update, delete or overwrite function in the ABI", async function () {
      const { ledger } = await loadFixture(deployFixture);
      const writeFns = ledger.interface.fragments
        .filter((f) => f.type === "function" && !["view", "pure"].includes(f.stateMutability))
        .map((f) => f.name);
      expect(writeFns).to.deep.equal(["appendRecord"]);
    });

    it("never changes an existing record when more are appended", async function () {
      const { ledger } = await loadFixture(deployFixture);
      await ledger.appendRecord(EventType.P2P_TRADE, fingerprint(tradePayload), "node_a");
      const before = await ledger.getRecord(0);
      for (let i = 0; i < 5; i++) {
        await ledger.appendRecord(EventType.FL_ROUND, fingerprint({ round: i }), "federated_server");
      }
      const after = await ledger.getRecord(0);
      expect(after.payloadHash).to.equal(before.payloadHash);
      expect(after.actor).to.equal(before.actor);
      expect(after.timestamp).to.equal(before.timestamp);
      expect(await ledger.recordCount()).to.equal(6n);
    });

    it("rejects appends from anyone but the owner", async function () {
      const { ledger, stranger } = await loadFixture(deployFixture);
      await expect(
        ledger.connect(stranger).appendRecord(EventType.P2P_TRADE, fingerprint(tradePayload), "x")
      ).to.be.revertedWithCustomError(ledger, "NotOwner");
    });

    it("rejects an empty hash, an empty actor and an unknown event type", async function () {
      const { ledger } = await loadFixture(deployFixture);
      await expect(ledger.appendRecord(EventType.P2P_TRADE, ethers.ZeroHash, "x")).to.be.revertedWithCustomError(
        ledger,
        "EmptyHash"
      );
      await expect(ledger.appendRecord(EventType.P2P_TRADE, fingerprint(tradePayload), "")).to.be.revertedWithCustomError(
        ledger,
        "EmptyActor"
      );
      await expect(ledger.appendRecord(9, fingerprint(tradePayload), "x")).to.be.reverted;
    });

    it("reverts on reading a record that does not exist", async function () {
      const { ledger } = await loadFixture(deployFixture);
      await expect(ledger.getRecord(0)).to.be.revertedWithCustomError(ledger, "UnknownRecord").withArgs(0);
    });
  });

  describe("event emission", function () {
    it("emits RecordAppended with id, type, hash, actor and recorder", async function () {
      const { ledger, owner } = await loadFixture(deployFixture);
      const h = fingerprint(tradePayload);
      await expect(ledger.appendRecord(EventType.P2P_TRADE, h, "wind_scada_kelmarsh_1"))
        .to.emit(ledger, "RecordAppended")
        .withArgs(0, EventType.P2P_TRADE, h, "wind_scada_kelmarsh_1", anyValue, owner.address);
    });
  });

  describe("hash verification", function () {
    it("matches the untouched payload and rejects a tampered copy", async function () {
      const { ledger } = await loadFixture(deployFixture);
      await ledger.appendRecord(EventType.P2P_TRADE, fingerprint(tradePayload), "wind_scada_kelmarsh_1");

      // Key order must not matter (canonical JSON).
      const reordered = Object.fromEntries(Object.entries(tradePayload).reverse());
      expect(await ledger.verify(0, fingerprint(reordered))).to.equal(true);

      const tampered = { ...tradePayload, kwh: 125 };
      expect(await ledger.verify(0, fingerprint(tampered))).to.equal(false);
    });

    it("uses the same canonical JSON form as the backend", async function () {
      // The backend (hashing.py) produces exactly this string for this object;
      // see the matching Python check in backend/app/blockchain/selftest.py.
      const obj = { b: 1, a: [1.5, "x"], c: { z: null, y: true } };
      expect(canonical(obj)).to.equal('{"a":[1.5,"x"],"b":1,"c":{"y":true,"z":null}}');
      expect(fingerprint(obj)).to.equal(
        ethers.keccak256(ethers.toUtf8Bytes('{"a":[1.5,"x"],"b":1,"c":{"y":true,"z":null}}'))
      );
    });
  });
});
