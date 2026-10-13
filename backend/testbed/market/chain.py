"""Web3.py client for the EnergyMarket contract on a local Hardhat node (separate from the EnergyLedger service).

Participants are LOCAL accounts (one per prosumer bus / microgrid node, funded through hardhat_setBalance) that sign their own
transactions; the owner and the gateway/oracle are the node's first two unlocked accounts. Every call records
(operation, gas used, latency seconds, block). Latency = wall time from submission to the receipt.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from eth_account import Account
from web3 import Web3

ROOT = Path(__file__).resolve().parents[3]
ARTIFACT = ROOT / "blockchain" / "artifacts" / "contracts" / "EnergyMarket.sol" / "EnergyMarket.json"


def node_id(name: str) -> bytes:
    return name.encode()[:32].ljust(32, b"\0")


class Market:
    def __init__(self, url: str = __import__("os").environ.get("SEI_RPC", "http://127.0.0.1:8545"), interval_mining_s: float | None = None):
        self.w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 120}))
        assert self.w3.is_connected(), "Hardhat node not reachable (npx hardhat node)"
        accts = self.w3.eth.accounts
        self.owner, self.gateway = accts[0], accts[1]
        art = json.loads(ARTIFACT.read_text())
        C = self.w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
        txh = C.constructor(self.gateway).transact({"from": self.owner})
        rc = self.w3.eth.wait_for_transaction_receipt(txh)
        self.deploy_gas = rc.gasUsed
        self.c = self.w3.eth.contract(address=rc.contractAddress, abi=art["abi"])
        self.records: list[dict] = []
        self.accounts: dict[str, Account] = {}
        self.interval_mining_s = interval_mining_s
        if interval_mining_s:
            self.w3.provider.make_request("evm_setAutomine", [False])
            self.w3.provider.make_request("evm_setIntervalMining", [int(interval_mining_s * 1000)])

    def new_account(self, name: str) -> Account:
        a = Account.create()
        self.w3.provider.make_request("hardhat_setBalance", [a.address, hex(10 ** 20)])
        self.accounts[name] = a
        return a

    def _send(self, op: str, fn, sender: Account | None, nonce_account: str | None = None):
        tx_args = {"from": (sender.address if sender else self.gateway)}
        t0 = time.perf_counter()
        if sender is None:  # unlocked node account (gateway)
            txh = fn.transact(tx_args)
        else:
            tx = fn.build_transaction({"from": sender.address, "nonce": self.w3.eth.get_transaction_count(sender.address), "gas": 500000,
                                       "gasPrice": self.w3.eth.gas_price, "chainId": self.w3.eth.chain_id})
            txh = self.w3.eth.send_raw_transaction(sender.sign_transaction(tx).raw_transaction)
        rc = self.w3.eth.wait_for_transaction_receipt(txh, timeout=300, poll_latency=0.01)
        dt = time.perf_counter() - t0
        self.records.append(dict(op=op, gas=int(rc.gasUsed), latency_s=dt, block=int(rc.blockNumber), status=int(rc.status)))
        return rc

    # ---- operations ----
    def register(self, acct: Account, name: str):
        return self._send("register", self.c.functions.register(node_id(name)), acct)

    def post_offer(self, acct: Account, wh: int, price_milli: int):
        rc = self._send("sell_offer", self.c.functions.postOffer(int(wh), int(price_milli)), acct)
        return self.c.events.OfferPosted().process_receipt(rc)[0]["args"]["id"]

    def post_bid(self, acct: Account, wh: int, price_milli: int):
        rc = self._send("buy_bid", self.c.functions.postBid(int(wh), int(price_milli)), acct)
        return self.c.events.BidPosted().process_receipt(rc)[0]["args"]["id"]

    def match(self, offer_id: int, bid_id: int):
        rc = self._send("match", self.c.functions.matchTrade(offer_id, bid_id), None)
        return self.c.events.TradeMatched().process_receipt(rc)[0]["args"]

    def meter(self, trade_id: int, seller_wh: int, buyer_wh: int):
        return self._send("meter", self.c.functions.submitMeter(trade_id, int(seller_wh), int(buyer_wh)), None)

    def settle(self, trade_id: int, caller: Account | None = None):
        rc = self._send("settle", self.c.functions.settle(trade_id), caller)
        return self.c.events.Settled().process_receipt(rc)[0]["args"]

    def advance(self):
        return self._send("advance_interval", self.c.functions.advanceInterval(), None)

    def expire_offer(self, oid: int, caller: Account):
        return self._send("expire_offer", self.c.functions.expireOffer(oid), caller)

    def balance(self, acct: Account) -> int:
        return int(self.c.functions.balanceMilli(acct.address).call())

    def summary(self) -> dict:
        out: dict[str, dict] = {}
        for r in self.records:
            o = out.setdefault(r["op"], dict(n=0, gas=[], lat=[]))
            o["n"] += 1
            o["gas"].append(r["gas"])
            o["lat"].append(r["latency_s"])
        import numpy as np
        return {op: dict(n=v["n"], gas_mean=float(np.mean(v["gas"])), gas_min=int(min(v["gas"])), gas_max=int(max(v["gas"])), latency_mean_s=float(np.mean(v["lat"])),
                         latency_p95_s=float(np.percentile(v["lat"], 95))) for op, v in out.items()}
