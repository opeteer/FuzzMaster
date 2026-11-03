// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "forge-std/Test.sol";
import "../src/VulnerableVault.sol";

contract VaultTest is Test {
    VulnerableVault public vault;
    address public user1 = address(0x1111);
    address public user2 = address(0x2222);

    function setUp() public {
        vault = new VulnerableVault{value: 5 ether}();
        vm.deal(user1, 10 ether);
        vm.deal(user2, 10 ether);
    }

    function testDeposit() public {
        vm.prank(user1);
        vault.deposit{value: 2 ether}();
        assertEq(vault.balances(user1), 2 ether);
        assertEq(vault.totalDeposited(), 7 ether);
    }

    function testWithdraw() public {
        vm.prank(user1);
        vault.deposit{value: 2 ether}();
        assertEq(vault.balances(user1), 2 ether);

        vm.prank(user1);
        vault.withdraw();
        assertEq(vault.balances(user1), 0);
        assertEq(user1.balance, 10 ether);
    }

    function testEmergencyWithdraw() public {
        vm.prank(user1);
        vault.deposit{value: 2 ether}();

        // user2 drains vault via emergencyWithdraw()
        uint256 initUser2Bal = user2.balance;
        vm.prank(user2);
        vault.emergencyWithdraw();
        assertEq(user2.balance, initUser2Bal + 7 ether);
    }

    function testSolvencyInvariant() public view {
        assertTrue(vault.check_solvency());
    }
}
