// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title VulnerableVault
 * @notice Vault contract with intentional vulnerabilities for fuzzing demonstration.
 * - Reentrancy flaw in withdrawAll()
 * - Invariant breach: totalDeposited > address(this).balance
 * - Unauthorized kill() condition triggering Selfdestruct oracle
 */
contract VulnerableVault {
    mapping(address => uint256) public balances;
    uint256 public totalDeposited;
    address public owner;
    bool public isLocked;

    event Deposited(address indexed user, uint256 amount);
    event Withdrawn(address indexed user, uint256 amount);
    event EmergencyUnlocked(address indexed sender);

    constructor() payable {
        owner = msg.sender;
        totalDeposited = msg.value;
    }

    /// @notice Standard deposit function
    function deposit() external payable {
        require(msg.value > 0, "Zero deposit");
        balances[msg.sender] += msg.value;
        totalDeposited += msg.value;
        emit Deposited(msg.sender, msg.value);
    }

    /// @notice Vulnerable withdraw function: state updated AFTER external call (Classic Reentrancy)
    function withdrawAll() external {
        uint256 balance = balances[msg.sender];
        require(balance > 0, "No balance");

        // External call before state update
        (bool success, ) = msg.sender.call{value: balance}("");
        require(success, "Transfer failed");

        balances[msg.sender] = 0;
        totalDeposited -= balance;

        emit Withdrawn(msg.sender, balance);
    }

    /// @notice Insecure emergency drain / kill
    function emergencyDrain(address payable recipient) external {
        // Flawed condition: anyone can call if contract balance exceeds 10 ether or if caller sends matching secret
        require(recipient != address(0), "Invalid recipient");
        require(address(this).balance >= 5 ether || msg.sender == owner, "Unauthorized");

        selfdestruct(recipient);
    }

    /// @notice Echidna / FuzzMaster Invariant check: Vault must remain solvent
    function echidna_solvency() external view returns (bool) {
        return address(this).balance >= totalDeposited;
    }

    /// @notice Solvency check function
    function check_solvency() external view returns (bool) {
        return address(this).balance >= totalDeposited;
    }

    receive() external payable {
        balances[msg.sender] += msg.value;
        totalDeposited += msg.value;
    }
}
