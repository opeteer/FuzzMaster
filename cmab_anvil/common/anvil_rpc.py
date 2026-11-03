"""
Universal Unprivileged JSON-RPC / Cast Client for the Anvil Simulator.

Enforces the Zero-Privilege User Model across any CMAB Agent:
  1. Uses an ordinary Externally Owned Account (EOA) identity (`AGENT_ADDR`).
  2. Cryptographically and on-chain verifies that `AGENT_ADDR` is NOT the contract owner.
  3. Prohibits calling any privileged `anvil_*`, `evm_*`, or `debug_*` cheatcode methods.
  4. Provides universal read-only state queries (`eth_call`, `eth_getBalance`, `eth_getCode`,
     `eth_blockNumber`) and standard signed EOA transaction submission (`cast send`).
"""

from pathlib import Path
import subprocess
from typing import Dict, List, Optional, Tuple


class UnprivilegedAnvilClient:
    """
    Universal RPC client for interacting with Anvil strictly as a normal EOA user.
    """

    # Anvil Account #0: Deployer / Owner (Strictly distinct from the CMAB Agent)
    DEPLOYER_ADDR: str = "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266"

    # Anvil Account #1: Peer Normal User (for optional background traffic simulation)
    PEER_USER_ADDR: str = "0x70997970C51812dc3A010C7d01b50e0d17dc79C8"
    PEER_USER_PK: str = "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d"

    # Anvil Account #2: Unprivileged Intelligent CMAB Agent
    DEFAULT_AGENT_ADDR: str = "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC"
    DEFAULT_AGENT_PK: str = "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a"

    FORBIDDEN_RPC_PREFIXES = ("anvil_", "evm_", "debug_", "hardhat_")

    def __init__(
        self,
        rpc_url: str = "http://127.0.0.1:8545",
        agent_address: Optional[str] = None,
        agent_private_key: Optional[str] = None,
        cast_bin: Optional[Path] = None,
    ):
        self.rpc_url = rpc_url
        self.agent_address = agent_address or self.DEFAULT_AGENT_ADDR
        self.agent_private_key = agent_private_key or self.DEFAULT_AGENT_PK
        self.cast_bin = (
            cast_bin
            if cast_bin is not None
            else Path.home() / ".foundry" / "bin" / "cast"
        )

    def _run_cast(self, args: List[str]) -> Tuple[str, str, int]:
        for token in args:
            for forbidden in self.FORBIDDEN_RPC_PREFIXES:
                if token.startswith(forbidden):
                    raise PermissionError(
                        f"Zero-Privilege Violation: Forbidden RPC cheatcode '{token}' blocked!"
                    )

        cmd = [str(self.cast_bin)] + args + ["--rpc-url", self.rpc_url]
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        return proc.stdout.strip(), proc.stderr.strip(), proc.returncode

    @staticmethod
    def parse_uint256_ether(raw_output: str) -> float:
        """Convert cast uint256 wei output string into float ETH/Token units (1e18)."""
        if not raw_output:
            return 0.0
        first_token = raw_output.split()[0].strip()
        try:
            return float(int(first_token, 0)) / 1e18
        except ValueError:
            return 0.0

    # -------------------------------------------------------------------------
    # Universal Zero-Privilege Verification
    # -------------------------------------------------------------------------
    def verify_not_owner(
        self,
        contract_address: str,
        owner_sig: str = "owner()(address)",
    ) -> Dict[str, str]:
        """
        Verify on-chain that `self.agent_address` is NOT the owner of `contract_address`.
        """
        owner_out, err, code = self._run_cast(["call", contract_address, owner_sig])
        if code != 0:
            raise RuntimeError(
                f"Failed to query {owner_sig} on {contract_address}: {err}"
            )

        contract_owner = owner_out.strip()
        if contract_owner.lower() == self.agent_address.lower():
            raise PermissionError(
                f"Privilege violation: Agent {self.agent_address} is the owner of {contract_address}!"
            )

        return {
            "agent_address": self.agent_address,
            "contract_address": contract_address,
            "contract_owner": contract_owner,
            "standing": "STRICT_UNPRIVILEGED_EOA",
        }

    # -------------------------------------------------------------------------
    # Universal Read-Only Public Queries (Zero Gas)
    # -------------------------------------------------------------------------
    def get_block_number(self) -> int:
        out, _, code = self._run_cast(["block-number"])
        if code != 0 or not out:
            return 0
        return int(out.split()[0])

    def get_eth_balance(self, address: str) -> float:
        out, _, code = self._run_cast(["balance", address])
        if code != 0:
            return 0.0
        return self.parse_uint256_ether(out)

    def get_code_alive(self, address: str) -> bool:
        out, _, code = self._run_cast(["code", address])
        return code == 0 and len(out) > 2 and out != "0x"

    def call_uint256_ether(
        self, contract_address: str, sig: str, *call_args: str
    ) -> float:
        cmd = ["call", contract_address, sig] + list(call_args)
        out, _, code = self._run_cast(cmd)
        if code != 0:
            return 0.0
        return self.parse_uint256_ether(out)

    def call_bool(
        self, contract_address: str, sig: str, *call_args: str
    ) -> Tuple[bool, bool]:
        """Returns (call_succeeded, bool_value)."""
        cmd = ["call", contract_address, sig] + list(call_args)
        out, _, code = self._run_cast(cmd)
        if code != 0:
            return False, False
        return True, ("true" in out.lower())

    # -------------------------------------------------------------------------
    # Universal Signed EOA Transaction Execution
    # -------------------------------------------------------------------------
    def send_eoa_transaction(
        self,
        target_address: str,
        function_sig: str = "",
        call_args: Optional[List[str]] = None,
        eth_value: float = 0.0,
        sender_private_key: Optional[str] = None,
    ) -> Tuple[bool, str]:
        """
        Sign and broadcast a standard EOA transaction to Anvil.
        """
        pk = sender_private_key or self.agent_private_key
        cast_args: List[str] = ["send", target_address]

        if function_sig:
            cast_args.append(function_sig)
            if call_args:
                cast_args.extend(call_args)

        if eth_value > 0.0:
            wei_val = int(round(eth_value * 1e18))
            cast_args.extend(["--value", str(wei_val)])

        cast_args.extend(["--private-key", pk])
        out, err, code = self._run_cast(cast_args)
        if code == 0:
            return True, out
        return False, err

