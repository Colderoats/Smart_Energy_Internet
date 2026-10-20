"""Synchronous Web3.py client for the EnergyMarket contract (same pattern as
app/blockchain/chain_client.py: every call blocks on network I/O and the market
service always calls it through `asyncio.to_thread`).

Access model of the UNCHANGED contract (read from EnergyMarket.sol):
  register(nodeId)            msg.sender = the prosumer's own account  -> one account per prosumer
  postOffer / postBid         registered prosumer account (sender)
  matchTrade                  gateway only
  submitMeter                 gateway only (the oracle)
  settle                      anyone (we send it from the gateway)
  advanceInterval             gateway only
So: account #0 is the owner AND the gateway/oracle (the backend's configured
local key), accounts #1..#4 are the four prosumers.

Those are HARDHAT'S PUBLIC DEV KEYS: local node only. They are never used for
Sepolia (the market refuses to start on any other network) and are not secrets.

Deployment: <repo>/blockchain/deployments/localhost-market.json. If the local
node was restarted (no code at the address), the contract is redeployed from the
compiled Hardhat artifact with gateway = account #0 and the file is rewritten.
(blockchain/scripts/deploy_market.js still works for manual deploys; it writes
market.<network>.json with the gateway set from MARKET_GATEWAY.)
"""

import json
import logging
import threading
from datetime import datetime, timezone

from eth_account import Account
from web3 import Web3
from web3.logs import DISCARD

from app.blockchain.chain_client import address_lock
from app.config import REPO_ROOT, settings

logger = logging.getLogger("sei")

DEPLOYMENT_FILE = REPO_ROOT / "blockchain" / "deployments" / "localhost-market.json"
ARTIFACT_PATH = REPO_ROOT / "blockchain" / "artifacts" / "contracts" / "EnergyMarket.sol" / "EnergyMarket.json"

# Hardhat's well-known dev accounts #1..#4 (public, local only).
HARDHAT_DEV_KEYS = [
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
    "0x7c852118294e51e653712a81e05800f419141751be58f605c371e15141b007a6",
    "0x47e179ec197488593b187f80a00eb0da91f1b9d0b13f8733639f19c30a34926a",
]
EVENT_NAMES = ["Registered", "OfferPosted", "BidPosted", "TradeMatched", "Metered", "Settled", "IntervalAdvanced",
               "OfferExpired", "BidExpired", "GatewayChanged"]


class MarketChainUnavailable(Exception):
    """Node unreachable / contract missing / not local: retry later."""


def node_id_bytes(name: str) -> bytes:
    return name.encode()[:32].ljust(32, b"\0")


def _hex(b) -> str:
    return "0x" + bytes(b).hex().removeprefix("0x")


class MarketChain:
    def __init__(self, prosumer_ids: list[str]) -> None:
        self.prosumer_ids = prosumer_ids
        self._lock = threading.Lock()
        self._w3: Web3 | None = None
        self._contract = None
        self._deployment: dict | None = None
        self.gateway: Account | None = None
        self.accounts: dict[str, Account] = {}
        self.chain_id: int | None = None
        self.contract_address: str | None = None
        self.deployment_key: str | None = None
        self.required_confirmations = settings.blockchain_confirmations_local

    # -- connection ---------------------------------------------------------

    def connect(self) -> None:
        if settings.blockchain_network.lower() != "local":
            raise MarketChainUnavailable("prosumer market runs on the local Hardhat node only (BLOCKCHAIN_NETWORK=local)")
        w3 = Web3(Web3.HTTPProvider(settings.blockchain_local_rpc_url, request_kwargs={"timeout": 10}))
        try:
            chain_id = w3.eth.chain_id
        except Exception as exc:
            raise MarketChainUnavailable(f"node unreachable at {settings.blockchain_local_rpc_url}: {type(exc).__name__}") from exc

        gateway = Account.from_key(settings.blockchain_local_private_key)
        dep = json.loads(DEPLOYMENT_FILE.read_text(encoding="utf-8")) if DEPLOYMENT_FILE.exists() else None
        if dep is None or dep.get("chainId") != chain_id or not self._valid(w3, dep, gateway):
            if not settings.blockchain_auto_deploy_local:
                raise MarketChainUnavailable("EnergyMarket not deployed (run deploy_market.js or enable BLOCKCHAIN_AUTO_DEPLOY_LOCAL)")
            dep = self._deploy(w3, gateway, chain_id)

        contract = w3.eth.contract(address=Web3.to_checksum_address(dep["address"]), abi=dep["abi"])
        self._w3, self._contract, self._deployment = w3, contract, dep
        self.gateway = gateway
        self.accounts = {nid: Account.from_key(HARDHAT_DEV_KEYS[i]) for i, nid in enumerate(self.prosumer_ids)}
        self.chain_id = chain_id
        self.contract_address = contract.address
        self.deployment_key = f"{contract.address}@{self._deploy_block_hash(w3, dep)}"

    @staticmethod
    def _deploy_block_hash(w3: Web3, dep: dict) -> str | None:
        try:
            rc = w3.eth.get_transaction_receipt(dep["txHash"])
        except Exception:
            return None
        if rc is None or rc["contractAddress"] is None or rc["contractAddress"].lower() != dep["address"].lower():
            return None
        return _hex(rc["blockHash"])

    def _valid(self, w3: Web3, dep: dict, gateway: Account) -> bool:
        """Code present at the address, deployed in a block of THIS chain, gateway = account #0."""
        try:
            if len(w3.eth.get_code(Web3.to_checksum_address(dep["address"]))) == 0:
                return False
            if self._deploy_block_hash(w3, dep) is None:
                return False
            c = w3.eth.contract(address=Web3.to_checksum_address(dep["address"]), abi=dep["abi"])
            return c.functions.gateway().call().lower() == gateway.address.lower()
        except Exception:
            return False

    def _deploy(self, w3: Web3, gateway: Account, chain_id: int) -> dict:
        if not ARTIFACT_PATH.exists():
            raise MarketChainUnavailable("EnergyMarket not compiled (run `npx hardhat compile` in blockchain/)")
        art = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        factory = w3.eth.contract(abi=art["abi"], bytecode=art["bytecode"])
        tx = factory.constructor(gateway.address).build_transaction(
            {"from": gateway.address, "nonce": w3.eth.get_transaction_count(gateway.address, "pending"), "chainId": chain_id}
        )
        rc = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(gateway.sign_transaction(tx).raw_transaction), timeout=60)
        dep = {
            "network": "localhost", "chainId": chain_id, "address": rc["contractAddress"], "deployer": gateway.address,
            "gateway": gateway.address, "blockNumber": rc["blockNumber"], "txHash": _hex(rc["transactionHash"]),
            "deployGas": int(rc["gasUsed"]),
            "deployedAt": datetime.now(timezone.utc).isoformat(),
            "deployedBy": "backend auto-deploy (no valid EnergyMarket on the local Hardhat node)",
            "abi": art["abi"],
        }
        DEPLOYMENT_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEPLOYMENT_FILE.write_text(json.dumps(dep, indent=2), encoding="utf-8")
        logger.info("Prosumer market: auto-deployed EnergyMarket to %s (gateway %s)", rc["contractAddress"], gateway.address)
        return dep

    def is_connected(self) -> bool:
        if self._w3 is None:
            return False
        try:
            if self._w3.eth.chain_id != self.chain_id:
                return False
            return self.deployment_key == f"{self.contract_address}@{self._deploy_block_hash(self._w3, self._deployment)}"
        except Exception:
            return False

    def ensure(self) -> None:
        if not self.is_connected():
            self._w3 = None
            self.connect()

    # -- reads --------------------------------------------------------------

    def block_number(self) -> int:
        self.ensure()
        return self._w3.eth.block_number

    def current_interval(self) -> int:
        self.ensure()
        return int(self._contract.functions.currentInterval().call())

    def account_of(self, node_id: str) -> str | None:
        self.ensure()
        a = self._contract.functions.accountOf(node_id_bytes(node_id)).call()
        return None if int(a, 16) == 0 else a

    def balance_milli(self, address: str) -> int:
        self.ensure()
        return int(self._contract.functions.balanceMilli(address).call())

    # -- writes (each returns the tx hash without waiting) -----------------------

    def _send(self, fn, account: Account) -> str:
        with self._lock, address_lock(account.address):  # shared with the ledger client (same account #0)
            self.ensure()
            tx = fn.build_transaction(
                {"from": account.address, "nonce": self._w3.eth.get_transaction_count(account.address, "pending"), "chainId": self.chain_id}
            )
            return _hex(self._w3.eth.send_raw_transaction(account.sign_transaction(tx).raw_transaction))

    def register(self, node_id: str) -> str:
        return self._send(self._contract.functions.register(node_id_bytes(node_id)), self.accounts[node_id])

    def post_offer(self, node_id: str, qty_wh: int, price_milli: int) -> str:
        return self._send(self._contract.functions.postOffer(int(qty_wh), int(price_milli)), self.accounts[node_id])

    def post_bid(self, node_id: str, qty_wh: int, price_milli: int) -> str:
        return self._send(self._contract.functions.postBid(int(qty_wh), int(price_milli)), self.accounts[node_id])

    def match_trade(self, offer_id: int, bid_id: int) -> str:
        return self._send(self._contract.functions.matchTrade(int(offer_id), int(bid_id)), self.gateway)

    def submit_meter(self, trade_id: int, seller_wh: int, buyer_wh: int) -> str:
        return self._send(self._contract.functions.submitMeter(int(trade_id), int(seller_wh), int(buyer_wh)), self.gateway)

    def settle(self, trade_id: int) -> str:
        return self._send(self._contract.functions.settle(int(trade_id)), self.gateway)

    def advance_interval(self) -> str:
        return self._send(self._contract.functions.advanceInterval(), self.gateway)

    # -- receipts -----------------------------------------------------------

    def get_receipt(self, tx_hash: str) -> dict | None:
        self.ensure()
        try:
            return self._receipt_dict(self._w3.eth.get_transaction_receipt(tx_hash))
        except Exception as exc:
            if "not found" in str(exc).lower() or type(exc).__name__ == "TransactionNotFound":
                return None
            raise

    def wait_receipt(self, tx_hash: str, timeout: float = 30) -> dict:
        self.ensure()
        return self._receipt_dict(self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout, poll_latency=0.3))

    def confirmations(self, block_number: int) -> int:
        return max(0, self.block_number() - block_number + 1)

    def _receipt_dict(self, receipt) -> dict:
        events = []
        for name in EVENT_NAMES:
            for ev in getattr(self._contract.events, name)().process_receipt(receipt, errors=DISCARD):
                events.append({"event": name, "args": {k: (_hex(v) if isinstance(v, (bytes, bytearray)) else v) for k, v in ev["args"].items()}})
        return {
            "status": int(receipt["status"]),
            "block_number": int(receipt["blockNumber"]),
            "block_hash": _hex(receipt["blockHash"]),
            "gas_used": int(receipt["gasUsed"]),
            "events": events,
        }

    def describe(self) -> dict:
        return {
            "contract_address": self.contract_address,
            "deployment_key": self.deployment_key,
            "chain_id": self.chain_id,
            "gateway": self.gateway.address if self.gateway else None,
            "deployed_at": (self._deployment or {}).get("deployedAt"),
            "deploy_tx_hash": (self._deployment or {}).get("txHash"),
            "deploy_block": (self._deployment or {}).get("blockNumber"),
            "deploy_gas": (self._deployment or {}).get("deployGas"),
        }
