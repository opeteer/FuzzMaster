// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Script.sol";
import "../src/VulnerableVault.sol";
import "../src/MockToken.sol";

contract DeployScript is Script {
    function run() external returns (VulnerableVault vault, MockToken token) {
        // Anvil default account #0 private key
        uint256 deployerPrivateKey = vm.envOr(
            "PRIVATE_KEY",
            uint256(0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80)
        );

        vm.startBroadcast(deployerPrivateKey);

        // Deploy Vault funded with 10 ETH initial liquidity
        vault = new VulnerableVault{value: 10 ether}();
        console.log("VulnerableVault deployed to:", address(vault));

        // Deploy MockToken with 1,000,000 supply
        token = new MockToken(1_000_000 ether);
        console.log("MockToken deployed to:", address(token));

        vm.stopBroadcast();
    }
}
