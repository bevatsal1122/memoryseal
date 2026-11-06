"""Submit a protected transfer directly to the enforcing contract.

The RPC is untrusted infrastructure; the contract enforces the current policy.
Transaction hashes indicate submission, not finality or successful execution.
"""

import re
from types import SimpleNamespace

import httpx
from eth_abi import decode, encode
from eth_abi.exceptions import DecodingError
from eth_account import Account
from eth_utils import is_address, keccak, to_checksum_address

from memoryseal.contract_artifacts import matches_local_runtime
from memoryseal.http_limits import read_json_limited


class RpcError(RuntimeError):
    pass


class SubmissionOutcomeUnknown(RpcError):
    """The signed transaction might have been accepted despite an RPC failure."""

    def __init__(self, transaction_hash: str):
        self.transaction_hash = transaction_hash
        super().__init__("Transaction submission is uncertain; check its hash before retrying.")


class ProtectedTransferClient:
    def __init__(
        self,
        rpc_url: str,
        private_key: str,
        *,
        chain_id: int,
        executor: str,
        max_gas_price_wei: int,
        transport=None,
    ):
        if chain_id <= 0 or max_gas_price_wei <= 0 or not is_address(executor):
            raise ValueError("invalid chain, executor, or gas price cap")
        self.account = Account.from_key(private_key)
        self.chain_id = chain_id
        self.executor = to_checksum_address(executor)
        self.max_gas_price_wei = max_gas_price_wei
        self.http = httpx.Client(base_url=rpc_url, transport=transport, timeout=30)
        self._id = 0

    def close(self):
        self.http.close()

    def _rpc(self, method: str, params: list):
        self._id += 1
        try:
            with self.http.stream(
                "POST",
                "",
                json={"jsonrpc": "2.0", "id": self._id, "method": method, "params": params},
            ) as response:
                body = read_json_limited(response, max_bytes=1_048_576)
            if (
                not isinstance(body, dict)
                or body.get("id") != self._id
                or "error" in body
                or "result" not in body
            ):
                raise RpcError(f"RPC {method} failed")
            return body["result"]
        except (httpx.HTTPError, ValueError, TypeError, AttributeError) as exc:
            raise RpcError(f"RPC {method} failed") from exc

    def execute(
        self,
        *,
        owner: str,
        token: str,
        recipient: str,
        amount: int,
        policy_version: int,
        max_gas: int = 300000,
        gas_limit: int | None = None,
        expected_registry: str | None = None,
        verify_runtime: bool = False,
    ) -> str:
        """Submit an action; explicit gas bypasses estimation and can succeed or revert."""
        if any(not is_address(value) for value in (owner, token, recipient)):
            raise ValueError("invalid address")
        if (
            type(amount) is not int
            or type(policy_version) is not int
            or type(max_gas) is not int
            or not 0 < amount < 2**256
            or not 0 <= policy_version < 2**256
            or max_gas <= 0
            or (
                gas_limit is not None
                and (type(gas_limit) is not int or not 21000 <= gas_limit <= max_gas)
            )
        ):
            raise ValueError("invalid amount, version, or gas limit")
        if int(self._rpc("eth_chainId", []), 16) != self.chain_id:
            raise RpcError("RPC chain ID mismatch")
        if self._rpc("eth_getCode", [self.executor, "latest"]) in ("0x", "0x0"):
            raise RpcError("executor has no code")
        if expected_registry is not None:
            if not is_address(expected_registry) or int(expected_registry, 16) == 0:
                raise ValueError("invalid expected registry")
            try:
                block = self._rpc("eth_getBlockByNumber", ["latest", False])
                number, block_hash = block["number"], block["hash"]
                executor_code = self._rpc("eth_getCode", [self.executor, number])
                if not isinstance(executor_code, str) or executor_code in ("0x", "0x0"):
                    raise RpcError("executor has no code at observed block")
                code = self._rpc("eth_getCode", [expected_registry, number])
                if not isinstance(code, str) or code in ("0x", "0x0"):
                    raise RpcError("expected registry has no code")
                if verify_runtime and (
                    matches_local_runtime("MemoryPolicyRegistry", code, expected_registry)
                    is not True
                    or matches_local_runtime("ProtectedTransfer", executor_code, expected_registry)
                    is not True
                ):
                    raise RpcError(
                        "contract runtime differs from local build or artifact unavailable"
                    )
                selector = "0x" + keccak(text="registry()")[:4].hex()
                result = self._rpc("eth_call", [{"to": self.executor, "data": selector}, number])
                if not isinstance(result, str) or not result.startswith("0x") or len(result) != 66:
                    raise RpcError("invalid executor registry response")
                actual = decode(["address"], bytes.fromhex(result[2:]))[0]
                if actual.lower() != expected_registry.lower():
                    raise RpcError("executor registry mismatch")
                checked = self._rpc("eth_getBlockByNumber", [number, False])
                if checked["hash"].lower() != block_hash.lower():
                    raise RpcError("registry check block reorganized")
            except (KeyError, TypeError, ValueError, AttributeError, DecodingError) as exc:
                raise RpcError("invalid executor registry observation") from exc
        selector = keccak(text="execute(address,address,address,uint256,uint256)")[:4]
        data = (
            "0x"
            + (
                selector
                + encode(
                    ["address", "address", "address", "uint256", "uint256"],
                    [owner, token, recipient, amount, policy_version],
                )
            ).hex()
        )
        tx_request = {
            "from": self.account.address,
            "to": self.executor,
            "data": data,
            "value": "0x0",
        }
        nonce = int(self._rpc("eth_getTransactionCount", [self.account.address, "pending"]), 16)
        gas_price = int(self._rpc("eth_gasPrice", []), 16)
        if gas_price <= 0 or gas_price > self.max_gas_price_wei:
            raise RpcError("gas price exceeds configured cap")
        if gas_limit is None:
            gas = int(self._rpc("eth_estimateGas", [tx_request]), 16)
            if gas <= 0 or gas > max_gas:
                raise RpcError("estimated gas exceeds configured cap")
        else:
            gas = gas_limit
        signed = self.account.sign_transaction(
            {
                "chainId": self.chain_id,
                "nonce": nonce,
                "to": self.executor,
                "data": data,
                "value": 0,
                "gas": gas,
                "gasPrice": gas_price,
            }
        )
        expected_hash = "0x" + signed.hash.hex().lower()
        try:
            tx_hash = self._rpc("eth_sendRawTransaction", ["0x" + signed.raw_transaction.hex()])
        except RpcError as exc:
            raise SubmissionOutcomeUnknown(expected_hash) from exc
        if not isinstance(tx_hash, str) or tx_hash.lower() != expected_hash:
            raise SubmissionOutcomeUnknown(expected_hash)
        return tx_hash

    def receipt(self, tx_hash: str) -> dict:
        """Return observed status and confirmations; RPC results are not cryptographic proofs."""
        if not re.fullmatch(r"0x[0-9a-fA-F]{64}", tx_hash):
            raise ValueError("invalid transaction hash")
        if int(self._rpc("eth_chainId", []), 16) != self.chain_id:
            raise RpcError("RPC chain ID mismatch")
        receipt = self._rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt is None:
            return {"status": "pending", "confirmations": 0}
        try:
            if (
                receipt["transactionHash"].lower() != tx_hash.lower()
                or receipt["from"].lower() != self.account.address.lower()
                or receipt["to"].lower() != self.executor.lower()
            ):
                raise RpcError("receipt does not match transaction context")
            status = int(receipt["status"], 16)
            if status not in (0, 1):
                raise ValueError("invalid receipt status")
            block_number = int(receipt["blockNumber"], 16)
            block = self._rpc("eth_getBlockByNumber", [receipt["blockNumber"], False])
            if block is None or block["hash"].lower() != receipt["blockHash"].lower():
                return {"status": "reorged", "confirmations": 0}
            latest = int(self._rpc("eth_blockNumber", []), 16)
            if latest < block_number:
                raise RpcError("RPC returned inconsistent block height")
            return {
                "status": "success" if status == 1 else "reverted",
                "confirmations": latest - block_number + 1,
                "block_number": block_number,
                "block_hash": receipt["blockHash"],
            }
        except (KeyError, TypeError, ValueError, AttributeError) as exc:
            raise RpcError("malformed transaction receipt") from exc

    def verify_transfer(
        self,
        tx_hash: str,
        *,
        owner: str,
        token: str,
        recipient: str,
        amount: int,
        policy_version: int,
    ) -> dict:
        """Match the expected transfer event in a successful canonical receipt."""
        if any(not is_address(value) for value in (owner, token, recipient)):
            raise ValueError("invalid address")
        status = self.receipt(tx_hash)
        if status["status"] == "reverted":
            transaction = self._rpc("eth_getTransactionByHash", [tx_hash])
            expected_input = (
                "0x"
                + (
                    keccak(text="execute(address,address,address,uint256,uint256)")[:4]
                    + encode(
                        ["address", "address", "address", "uint256", "uint256"],
                        [owner, token, recipient, amount, policy_version],
                    )
                ).hex()
            )
            try:
                matches = (
                    transaction["hash"].lower() == tx_hash.lower()
                    and transaction["from"].lower() == self.account.address.lower()
                    and transaction["to"].lower() == self.executor.lower()
                    and transaction["input"].lower() == expected_input.lower()
                    and int(transaction["value"], 16) == 0
                    and transaction["blockHash"].lower() == status["block_hash"].lower()
                    and int(transaction["blockNumber"], 16) == status["block_number"]
                )
                block = self._rpc("eth_getBlockByNumber", [hex(status["block_number"]), False])
                if not block or block.get("hash", "").lower() != status["block_hash"].lower():
                    return {"status": "reorged", "confirmations": 0, "transfer_verified": False}
                return {**status, "transfer_verified": False, "reverted_call_verified": matches}
            except (KeyError, TypeError, ValueError, AttributeError) as exc:
                raise RpcError("malformed reverted transaction") from exc
        if status["status"] != "success":
            return {**status, "transfer_verified": False}
        # Fetch again and bind it to the same block in case a reorg happened
        # between calls; a later reorg remains possible.
        receipt = self._rpc("eth_getTransactionReceipt", [tx_hash])
        if not receipt or receipt.get("blockHash", "").lower() != status["block_hash"].lower():
            return {"status": "reorged", "confirmations": 0, "transfer_verified": False}
        if (
            receipt.get("transactionHash", "").lower() != tx_hash.lower()
            or receipt.get("status") != "0x1"
            or receipt.get("from", "").lower() != self.account.address.lower()
            or receipt.get("to", "").lower() != self.executor.lower()
        ):
            raise RpcError("receipt changed during verification")
        event_topic = (
            "0x"
            + keccak(text="TransferExecuted(address,address,address,address,uint256,uint256)").hex()
        )

        def topic(address):
            return "0x" + address.lower().removeprefix("0x").zfill(64)

        expected_topics = [event_topic, topic(owner), topic(self.account.address), topic(token)]
        try:
            for log in receipt["logs"]:
                if log.get("removed", False):
                    continue
                if (
                    log["address"].lower() != self.executor.lower()
                    or [t.lower() for t in log["topics"]] != expected_topics
                ):
                    continue
                actual_recipient, actual_amount, actual_version = decode(
                    ["address", "uint256", "uint256"], bytes.fromhex(log["data"].removeprefix("0x"))
                )
                if (
                    actual_recipient.lower() == recipient.lower()
                    and actual_amount == amount
                    and actual_version == policy_version
                ):
                    token_topics = [
                        "0x" + keccak(text="Transfer(address,address,uint256)").hex(),
                        topic(owner),
                        topic(recipient),
                    ]
                    expected_amount = "0x" + encode(["uint256"], [amount]).hex()
                    token_event = any(
                        not entry.get("removed", False)
                        and entry["address"].lower() == token.lower()
                        and [value.lower() for value in entry["topics"]] == token_topics
                        and entry["data"].lower() == expected_amount
                        for entry in receipt["logs"]
                    )
                    return {
                        **status,
                        "transfer_verified": True,
                        "token_transfer_event_matched": token_event,
                    }
        except (KeyError, ValueError, TypeError, AttributeError, DecodingError) as exc:
            raise RpcError("malformed transfer event") from exc
        return {**status, "transfer_verified": False}


class OnchainReceiptVerifier(ProtectedTransferClient):
    """Read-only verifier using an expected signer address, with no signing key."""

    def __init__(self, rpc_url: str, signer: str, *, chain_id: int, executor: str, transport=None):
        if chain_id <= 0 or not is_address(signer) or not is_address(executor):
            raise ValueError("invalid chain, signer, or executor")
        self.account = SimpleNamespace(address=to_checksum_address(signer))
        self.chain_id = chain_id
        self.executor = to_checksum_address(executor)
        self.http = httpx.Client(base_url=rpc_url, transport=transport, timeout=30)
        self._id = 0

    def execute(self, **_kwargs):
        raise RuntimeError("receipt verifier cannot sign transactions")

    def verify_transfer_grant(
        self,
        tx_hash: str,
        *,
        agent: str,
        token: str,
        max_amount: int,
        expires_at: int,
        version: int,
    ) -> dict:
        """Observe a direct owner registry call and its matching capability event.

        The configured RPC is trusted for transaction and block data. This is not finality.
        """
        if any(not is_address(value) for value in (agent, token)):
            raise ValueError("invalid address")
        if not 0 < max_amount < 2**256 or not 0 <= expires_at < 2**64 or not 0 <= version < 2**256:
            raise ValueError("invalid capability fields")
        status = self.receipt(tx_hash)
        if status["status"] != "success":
            return {**status, "grant_verified": False}
        tx = self._rpc("eth_getTransactionByHash", [tx_hash])
        receipt = self._rpc("eth_getTransactionReceipt", [tx_hash])
        expected = (
            "0x"
            + (
                keccak(text="setTransferCapability(address,address,uint256,uint64)")[:4]
                + encode(
                    ["address", "address", "uint256", "uint64"],
                    [agent, token, max_amount, expires_at],
                )
            ).hex()
        )

        def topic(address):
            return "0x" + address.lower().removeprefix("0x").zfill(64)

        topics = [
            "0x"
            + keccak(
                text="TransferCapabilityChanged(address,address,address,uint256,uint64,bool,uint256)"
            ).hex(),
            topic(self.account.address),
            topic(agent),
            topic(token),
        ]
        try:
            matched = (
                tx["hash"].lower() == tx_hash.lower()
                and tx["from"].lower() == self.account.address.lower()
                and tx["to"].lower() == self.executor.lower()
                and tx["input"].lower() == expected.lower()
                and int(tx["value"], 16) == 0
                and tx["blockHash"].lower() == status["block_hash"].lower()
                and int(tx["blockNumber"], 16) == status["block_number"]
                and receipt["transactionHash"].lower() == tx_hash.lower()
                and receipt["blockHash"].lower() == status["block_hash"].lower()
                and receipt["status"] == "0x1"
                and receipt["from"].lower() == self.account.address.lower()
                and receipt["to"].lower() == self.executor.lower()
            )
            if matched:
                matched = any(
                    not log.get("removed", False)
                    and log["address"].lower() == self.executor.lower()
                    and [value.lower() for value in log["topics"]] == topics
                    and decode(
                        ["uint256", "uint64", "bool", "uint256"],
                        bytes.fromhex(log["data"].removeprefix("0x")),
                    )
                    == (max_amount, expires_at, False, version)
                    for log in receipt["logs"]
                )
            block = self._rpc("eth_getBlockByNumber", [hex(status["block_number"]), False])
            if not block or block.get("hash", "").lower() != status["block_hash"].lower():
                return {"status": "reorged", "confirmations": 0, "grant_verified": False}
            return {**status, "grant_verified": matched}
        except (KeyError, TypeError, ValueError, AttributeError, DecodingError) as exc:
            raise RpcError("malformed policy transaction or event") from exc
