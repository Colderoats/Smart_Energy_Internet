const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");

const id = (s) => ethers.encodeBytes32String(s);

async function fixture() {
  const [owner, gateway, seller, buyer, stranger, other] = await ethers.getSigners();
  const m = await (await ethers.getContractFactory("EnergyMarket")).deploy(gateway.address);
  await m.connect(seller).register(id("bus_solar_3"));
  await m.connect(buyer).register(id("bus_load_2"));
  return { m, owner, gateway, seller, buyer, stranger, other };
}

describe("EnergyMarket", function () {
  describe("registration", function () {
    it("registers an account against a node id and emits an event", async function () {
      const { m, stranger } = await loadFixture(fixture);
      await expect(m.connect(stranger).register(id("bus_9"))).to.emit(m, "Registered").withArgs(stranger.address, id("bus_9"));
      expect(await m.nodeOf(stranger.address)).to.equal(id("bus_9"));
    });
    it("rejects a second registration and a reused node id", async function () {
      const { m, seller, stranger } = await loadFixture(fixture);
      await expect(m.connect(seller).register(id("x"))).to.be.revertedWithCustomError(m, "AlreadyRegistered");
      await expect(m.connect(stranger).register(id("bus_solar_3"))).to.be.revertedWithCustomError(m, "NodeIdTaken");
    });
  });

  describe("offers and bids: registered accounts only", function () {
    it("lets registered accounts post and emits events", async function () {
      const { m, seller, buyer } = await loadFixture(fixture);
      await expect(m.connect(seller).postOffer(5000, 110)).to.emit(m, "OfferPosted").withArgs(0, seller.address, 0, 5000, 110);
      await expect(m.connect(buyer).postBid(4000, 130)).to.emit(m, "BidPosted").withArgs(0, buyer.address, 0, 4000, 130);
    });
    it("rejects unregistered accounts and zero quantities", async function () {
      const { m, stranger, seller } = await loadFixture(fixture);
      await expect(m.connect(stranger).postOffer(1, 1)).to.be.revertedWithCustomError(m, "NotRegistered");
      await expect(m.connect(stranger).postBid(1, 1)).to.be.revertedWithCustomError(m, "NotRegistered");
      await expect(m.connect(seller).postOffer(0, 1)).to.be.revertedWithCustomError(m, "ZeroQuantity");
    });
  });

  describe("matching", function () {
    it("matches price-compatible offer and bid for min(remaining) at the seller's ask", async function () {
      const { m, gateway, seller, buyer } = await loadFixture(fixture);
      await m.connect(seller).postOffer(5000, 110);
      await m.connect(buyer).postBid(4000, 130);
      await expect(m.connect(gateway).matchTrade(0, 0)).to.emit(m, "TradeMatched").withArgs(0, 0, 0, 4000, 110);
      expect((await m.getOffer(0)).remainWh).to.equal(1000);
      expect((await m.getBid(0)).remainWh).to.equal(0);
    });
    it("is gateway-only and refuses an ask above the bid", async function () {
      const { m, gateway, seller, buyer, stranger } = await loadFixture(fixture);
      await m.connect(seller).postOffer(5000, 140);
      await m.connect(buyer).postBid(4000, 130);
      await expect(m.connect(stranger).matchTrade(0, 0)).to.be.revertedWithCustomError(m, "NotGateway");
      await expect(m.connect(gateway).matchTrade(0, 0)).to.be.revertedWithCustomError(m, "PriceMismatch");
    });
  });

  describe("metering and settlement: Pay = p * min(q_s, q_b)", function () {
    async function matched() {
      const f = await fixture();
      await f.m.connect(f.seller).postOffer(5000, 110);
      await f.m.connect(f.buyer).postBid(5000, 130);
      await f.m.connect(f.gateway).matchTrade(0, 0);
      return f;
    }
    it("accepts metered quantities only from the gateway/oracle", async function () {
      const { m, seller, stranger, gateway } = await loadFixture(matched);
      await expect(m.connect(seller).submitMeter(0, 5000, 5000)).to.be.revertedWithCustomError(m, "NotGateway");
      await expect(m.connect(stranger).submitMeter(0, 5000, 5000)).to.be.revertedWithCustomError(m, "NotGateway");
      await expect(m.connect(gateway).submitMeter(0, 5000, 5000)).to.emit(m, "Metered").withArgs(0, 5000, 5000);
    });
    it("cannot settle before metering, and settles once", async function () {
      const { m, gateway } = await loadFixture(matched);
      await expect(m.settle(0)).to.be.revertedWithCustomError(m, "NotMetered");
      await m.connect(gateway).submitMeter(0, 5000, 5000);
      await m.settle(0);
      await expect(m.settle(0)).to.be.revertedWithCustomError(m, "AlreadySettled");
    });
    it("pays p * min(q_s, q_b) of the METERED quantities, not the matched quantity", async function () {
      const { m, gateway, seller, buyer } = await loadFixture(matched);
      await m.connect(gateway).submitMeter(0, 4200, 3800); // seller delivered 4.2 kWh, buyer received 3.8 kWh
      // 110 milli/kWh * 3800 Wh / 1000 = 418
      await expect(m.settle(0)).to.emit(m, "Settled").withArgs(0, seller.address, buyer.address, 3800, 418);
      expect(await m.balanceMilli(seller.address)).to.equal(418);
      expect(await m.balanceMilli(buyer.address)).to.equal(-418);
    });
    it("a second meter submission for the same trade is rejected", async function () {
      const { m, gateway } = await loadFixture(matched);
      await m.connect(gateway).submitMeter(0, 1, 1);
      await expect(m.connect(gateway).submitMeter(0, 2, 2)).to.be.revertedWithCustomError(m, "AlreadyMetered");
    });
  });

  describe("expiry at the end of the interval", function () {
    it("an unmatched offer expires once the interval advances, and cannot be matched afterwards", async function () {
      const { m, gateway, seller, buyer } = await loadFixture(fixture);
      await m.connect(seller).postOffer(5000, 110);
      await expect(m.expireOffer(0)).to.be.revertedWithCustomError(m, "StillOpen");
      await expect(m.connect(buyer).advanceInterval()).to.be.revertedWithCustomError(m, "NotGateway");
      await expect(m.connect(gateway).advanceInterval()).to.emit(m, "IntervalAdvanced").withArgs(1);
      await expect(m.expireOffer(0)).to.emit(m, "OfferExpired").withArgs(0, 5000);
      await m.connect(buyer).postBid(5000, 130);
      await expect(m.connect(gateway).matchTrade(0, 0)).to.be.revertedWithCustomError(m, "WrongInterval");
      await expect(m.expireOffer(0)).to.be.revertedWithCustomError(m, "AlreadyExpired");
    });
  });

  describe("gateway management", function () {
    it("only the owner can change the gateway", async function () {
      const { m, owner, stranger, other } = await loadFixture(fixture);
      await expect(m.connect(stranger).setGateway(other.address)).to.be.revertedWithCustomError(m, "NotOwner");
      await m.connect(owner).setGateway(other.address);
      expect(await m.gateway()).to.equal(other.address);
    });
  });
});
