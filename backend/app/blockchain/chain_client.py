"""Thin synchronous Web3.py wrapper around the EnergyLedger contract.

All methods block on network I/O; the ledger service always calls them via
`asyncio.to_thread`, so a slow or unreachable node never stalls the event loop
(ingestion, twin, WebSocket pushes keep running).

Contract address + ABI come from <repo>/blockchain/deployments/<network>.json,
written by `npm run deploy:local|deploy:sepolia`. On the local Hardhat node the
chain is wiped on every restart; with BLOCKCHAIN_AUTO_DEPLOY_LOCAL the client
redeploys from the compiled Hardhat artifact and rewrites that file.
"""

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path

from web3 import Web3

from app.config import REPO_ROOT, settings

logger = logging.getLogger("sei")

BLOCKCHAIN_DIR = REPO_ROOT / "blockchain"
ARTIFACT_PATH = BLOCKCHAIN_DIR / "artifacts" / "contracts" / "EnergyLedger.sol" / "EnergyLedger.json"

# Solidity enum order in EnergyLedger.sol — must match.
EVENT_TYPES = ["ENERGY_REDISTRIBUTION", "P2P_TRADE", "FAULT_ALERT", "FL_ROUND"]


class ChainUnavailable(Exception):
    """Node unreachable, not configured, or contract missing — retry later."""


class ChainClient:
    def __init__(self) -> None:
        self.network = settings.blockchain_network.lower()
        if self.network not in ("local", "sepolia"):
            raise ValueError(f"BLOCKCHAIN_NETWORK must be 'local' or 'sepolia', got {self.network!r}")
        self.deployment_file = BLOCKCHAIN_DIR / "deployments" / ("localhost.json" if self.network == "local" else "sepolia.json")
        self.required_confirmations = (
            settings.blockchain_confirmations_local if self.network == "local" else settings.blockchain_confirmations_sepolia
        )
        self._lock = threading.Lock()  # one tx at a time -> no nonce races
        self._w3: Web3 | None = None
        self._contract = None
        self._account = None
        self.chain_id: int | None = None
        self.contract_address: str | None = None
        self.deployment_key: str | None = None
        self._deployment: dict | None = None
        self.last_error: str | None = None

    # -- configuration --------------------------------------------------

    @property
    def rpc_url(self) -> str:
        return settings.blockchain_local_rpc_url if self.network == "local" else settings.sepolia_rpc_url

    def _private_key(self) -> str:
        key = settings.blockchain_local_private_key if self.network == "local" else settings.sepolia_private_key
        if not key:
            raise ChainUnavailable("SEPOLIA_PRIVATE_KEY is not set")
        return key if key.startswith("0x") else "0x" + key

    def explorer_tx_url(self, tx_hash: str | None) -> str | None:
        if not tx_hash or self.network != "sepolia":
            return None
        return f"https://sepolia.etherscan.io/tx/{tx_hash}"

    # -- connection -----------------------------------------------------

    def connect(self) -> None:
        """(Re)connect and make sure the contract exists at the recorded address.
        Raises ChainUnavailable with a readable reason otherwise."""
        if not self.rpc_url:
            raise ChainUnavailable("SEPOLIA_RPC_URL is not set")
        w3 = Web3(Web3.HTTPProvider(self.rpc_url, request_kwargs={"timeout": 10}))
        try:
            chain_id = w3.eth.chain_id
        except Exception as exc:
            raise ChainUnavailable(f"node unreachable at {self.rpc_url}: {type(exc).__name__}") from exc

        account = w3.eth.account.from_key(self._private_key())
        deployment = self._load_deployment()
        if (deployment is None or deployment.get("chainId") != chain_id
                or not self._has_code(w3, deployment.get("address"))
                or self._deployment_block_hash(w3, deployment) is None):
            if self.network == "local" and settings.blockchain_auto_deploy_local:
                deployment = self._deploy_local(w3, account, chain_id)
            else:
                raise ChainUnavailable(
                    f"EnergyLedger not deployed on {self.network} "
                    f"(run `npm run deploy:{'local' if self.network == 'local' else 'sepolia'}` in blockchain/)"
                )

        contract = w3.eth.contract(address=Web3.to_checksum_address(deployment["address"]), abi=deployment["abi"])
        owner = contract.functions.owner().call()
        if owner.lower() != account.address.lower():
            raise ChainUnavailable(f"configured key {account.address} is not the contract owner {owner}")

        self._w3, self._contract, self._account = w3, contract, account
        self.chain_id = chain_id
        self.contract_address = contract.address
        self._deployment = deployment
        self.deployment_key = f"{contract.address}@{self._deployment_block_hash(w3, deployment)}"
        self.last_error = None

    @staticmethod
    def _deployment_block_hash(w3: Web3, deployment: dict) -> str | None:
        """Hash of the block holding the contract's deployment tx on the chain
        we are connected to, or None if that tx is not on this chain.

        A restarted Hardhat node redeploys to the SAME address (same deployer,
        nonce 0), so the address alone cannot tell two local chains apart; the
        deployment block hash (it includes the block timestamp) can."""
        tx_hash = deployment.get("txHash")
        if not tx_hash:
            return None
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
        except Exception:
            return None
        if receipt is None or receipt["contractAddress"] is None:
            return None
        if receipt["contractAddress"].lower() != deployment["address"].lower():
            return None
        return "0x" + bytes(receipt["blockHash"]).hex().removeprefix("0x")

    def is_connected(self) -> bool:
        if self._w3 is None:
            return False
        try:
            chain_id = self._w3.eth.chain_id
            # A restarted local node keeps chain id 31337 but loses the contract
            # (or gets a fresh one at the same address): compare the deployment key.
            if chain_id != self.chain_id:
                return False
            block_hash = self._deployment_block_hash(self._w3, self._deployment)
            return block_hash is not None and self.deployment_key == f"{self.contract_address}@{block_hash}"
        except Exception:
            return False

    def ensure(self) -> None:
        if not self.is_connected():
            self._w3 = None
            self.connect()

    def _load_deployment(self) -> dict | None:
        if not self.deployment_file.exists():
            return None
        return json.loads(self.deployment_file.read_text(encoding="utf-8"))

    @staticmethod
    def _has_code(w3: Web3, address: str | None) -> bool:
        if not address:
            return False
        return len(w3.eth.get_code(Web3.to_checksum_address(address))) > 0

    def _deploy_local(self, w3: Web3, account, chain_id: int) -> dict:
        if not ARTIFACT_PATH.exists():
            raise ChainUnavailable("contract not compiled (run `npx hardhat compile` in blockchain/)")
        artifact = json.loads(ARTIFACT_PATH.read_text(encoding="utf-8"))
        factory = w3.eth.contract(abi=artifact["abi"], bytecode=artifact["bytecode"])
        tx = factory.constructor().build_transaction(
            {"from": account.address, "nonce": w3.eth.get_transaction_count(account.address, "pending"), "chainId": chain_id}
        )
        signed = account.sign_transaction(tx)
        receipt = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction), timeout=60)
        deployment = {
            "network": "localhost",
            "chainId": chain_id,
            "address": receipt["contractAddress"],
            "deployer": account.address,
            "blockNumber": receipt["blockNumber"],
            "txHash": "0x" + bytes(receipt["transactionHash"]).hex().removeprefix("0x"),
            "deployedAt": datetime.now(timezone.utc).isoformat(),
            "deployedBy": "backend auto-deploy (local Hardhat node had no contract)",
            "abi": artifact["abi"],
        }
        self.deployment_file.parent.mkdir(parents=True, exist_ok=True)
        self.deployment_file.write_text(json.dumps(deployment, indent=2), encoding="utf-8")
        logger.info("Module 5: auto-deployed EnergyLedger to %s on local Hardhat node", receipt["contractAddress"])
        return deployment

    # -- reads ----------------------------------------------------------

    def block_number(self) -> int:
        self.ensure()
        return self._w3.eth.block_number

    def record_count(self) -> int:
        self.ensure()
        return self._contract.functions.recordCount().call()

    def get_record(self, chain_record_id: int) -> dict:
        self.ensure()
        r = self._contract.functions.getRecord(chain_record_id).call()
        # struct Record {id, eventType, payloadHash, actor, timestamp, recorder}
        return {
            "id": r[0],
            "event_type": EVENT_TYPES[r[1]],
            "payload_hash": "0x" + bytes(r[2]).hex(),
            "actor": r[3],
            "timestamp": r[4],
            "recorder": r[5],
        }

    def get_receipt(self, tx_hash: str) -> dict | None:
        self.ensure()
        try:
            receipt = self._w3.eth.get_transaction_receipt(tx_hash)
        except Exception as exc:
            if "not found" in str(exc).lower() or type(exc).__name__ == "TransactionNotFound":
                return None
            raise
        return self._receipt_dict(receipt)

    def block_timestamp(self, block_number: int) -> datetime:
        self.ensure()
        ts = self._w3.eth.get_block(block_number)["timestamp"]
        return datetime.fromtimestamp(ts, tz=timezone.utc)

    # -- writes ---------------------------------------------------------

    def send_append(self, event_type: str, payload_hash: str, actor: str) -> str:
        """Sign + broadcast appendRecord. Returns the tx hash without waiting."""
        with self._lock:
            self.ensure()
            fn = self._contract.functions.appendRecord(EVENT_TYPES.index(event_type), bytes.fromhex(payload_hash[2:]), actor)
            tx = fn.build_transaction(
                {
                    "from": self._account.address,
                    "nonce": self._w3.eth.get_transaction_count(self._account.address, "pending"),
                    "chainId": self.chain_id,
                }
            )
            signed = self._account.sign_transaction(tx)
            tx_hash = self._w3.eth.send_raw_transaction(signed.raw_transaction)
            return "0x" + bytes(tx_hash).hex().removeprefix("0x")

    def wait_receipt(self, tx_hash: str, timeout: float) -> dict:
        self.ensure()
        receipt = self._w3.eth.wait_for_transaction_receipt(tx_hash, timeout=timeout, poll_latency=0.5)
        return self._receipt_dict(receipt)

    def _receipt_dict(self, receipt) -> dict:
        chain_record_id = None
        if receipt["status"] == 1:
            events = self._contract.events.RecordAppended().process_receipt(receipt)
            if events:
                chain_record_id = int(events[0]["args"]["id"])
        return {
            "status": int(receipt["status"]),
            "block_number": int(receipt["blockNumber"]),
            "block_hash": "0x" + bytes(receipt["blockHash"]).hex().removeprefix("0x"),
            "gas_used": int(receipt["gasUsed"]),
            "chain_record_id": chain_record_id,
        }

    def describe(self) -> dict:
        return {
            "network": self.network,
            "network_label": "Local Hardhat node (dev chain)" if self.network == "local" else "Ethereum Sepolia testnet",
            "rpc_url": self.rpc_url if self.network == "local" else "(from SEPOLIA_RPC_URL)",
            "chain_id": self.chain_id,
            "contract_address": self.contract_address,
            "deployment_key": self.deployment_key,
            "recorder_address": self._account.address if self._account else None,
            "required_confirmations": self.required_confirmations,
        }
