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
    /// Follows SC-Bench Vault_and_Liquidity dataset standard naming (`withdraw`)
    function withdraw() external {
        _withdraw(balances[msg.sender]);
    }

    /// @notice Parameterized withdraw variant following SC-Bench Vault_and_Liquidity dataset
    function withdraw(uint256 amount) external {
        _withdraw(amount);
    }

    /// @notice Backward compatibility alias
    function withdrawAll() external {
        _withdraw(balances[msg.sender]);
    }

    function _withdraw(uint256 amount) internal {
        require(amount > 0, "No balance");
        require(balances[msg.sender] >= amount, "Insufficient user balance");

        // External call before state update
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "Transfer failed");

        balances[msg.sender] -= amount;
        totalDeposited -= amount;

        emit Withdrawn(msg.sender, amount);
    }

    /// @notice Insecure emergency withdraw following SC-Bench Vault_and_Liquidity dataset standard
    function emergencyWithdraw() external {
        _emergencyWithdraw(payable(msg.sender));
    }

    function emergencyWithdraw(address payable recipient) external {
        _emergencyWithdraw(recipient);
    }

    /// @notice Backward compatibility alias for emergencyWithdraw
    function emergencyDrain(address payable recipient) external {
        _emergencyWithdraw(recipient);
    }

    function _emergencyWithdraw(address payable recipient) internal {
        // Flawed condition: anyone can call if contract balance exceeds 5 ether or if caller is owner
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
