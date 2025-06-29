# Escrow Bridge Frontend

The SettlementInitForm React Component is a form which allows users to initialize a USDC-based settlement by connecting their wallet, inputting an email and amount, and submitting a transaction to a deployed smart contract. It interacts with a backend API and uses MetaMask for wallet access.

**SettlementInitForm.tsx** is located in settlement-ui/src/components

---

## Constants & State Variables

### `walletAddress`

- **Purpose:** Stores the user's connected wallet address.
- **Set by:** `connectWallet()`
- **Used for:**
  - Displaying the wallet connection status.
  - Deriving a unique `settlementId` for the transaction.

---

### `usdcBalance`

- **Purpose:** Displays the USDC balance of the connected wallet.
- **Set by:** `fetchBalances()`
  ```ts
  const tokenBalanceRaw = await usdcContract.balanceOf(address);
  setUsdcBalance(ethers.utils.formatUnits(tokenBalanceRaw, 6));
  ```
- **Used in UI:**
  ```tsx
  Wallet USDC Balance: {usdcBalance}
  ```

---

### `contractUsdcBalance`

- **Purpose:** Reflects the USDC balance held by the smart contract.
- **Set by:** `fetchBalances()`
  ```ts
  const rawContractUsdcBalance = await contract.getUsdcBalance();
  setContractUsdcBalance(ethers.utils.formatUnits(rawContractUsdcBalance, 6));
  ```
- **Used in UI:**
  ```tsx
  Contract USDC Balance: {contractUsdcBalance}
  ```

---

### `freeBalance`

- **Purpose:** Shows the contract's available balance that can be used for new settlements.
- **Set by:** `fetchBalances()`
  ```ts
  const rawFreeBalance = await contract.getFreeBalance();
  setFreeBalance(ethers.utils.formatUnits(rawFreeBalance, 6));
  ```
- **Used for:**
  - Display in UI
  - Pre-submission validation:
    ```ts
    if (rawFreeBalance.lt(rawAmount)) {
      setStatus(
        "Insufficient contract free balance to process this settlement."
      );
      return;
    }
    ```

---

### `email`

- **Purpose:** Captures the user's email address.
- **Set by:** form input.
- **Used for:**
  - Generating a hashed identifier (`userEmailHash`)
  - Sending metadata to backend via `POST /api/store_salt`

---

### `amount`

- **Purpose:** Specifies how much USDC to settle.
- **Set by:** form input.
- **Used for:**
  - Parsing to a raw token value:
    ```ts
    const rawAmount = ethers.utils.parseUnits(amount, decimals);
    ```
  - Passed into the smart contract's `initPayment(...)` function.

---

### `status`

- **Purpose:** Provides real-time feedback in the UI.
- **Set throughout** the flow with messages like:
  - `"Processing..."`
  - `"Transaction confirmed!"`
  - `"Settlement completed"`
  - Errors or timeouts.

---

### `generateSalt`

- **Purpose:** Generates a random salt for unique ID hashing.
- **Used to compute:**
  - `idHash`: settlement identifier
  - `userEmailHash`: user-bound email hash

---

## Component Flow

1. **Connect Wallet**

   - Connects to MetaMask and fetches the user's wallet address and balances.

2. **Fill Form**

   - User inputs an email and USDC amount.

3. **Submit Payment**
   - Validates contract's free balance.
   - Generates salt and hashes.
   - Sends salt/email metadata to backend.
   - Calls `initPayment(...)` on the smart contract.
   - Waits for transaction confirmation.
   - Polls backend for final settlement result.

---

## Backend API

- `POST /api/store_salt`
- `POST /status`

---

## Constants Used in API Calls

```ts
const BACKEND_API = "http://localhost:5045";
```

---

## Dependencies

- **ethers.js** for Web3 interaction
- **MetaMask** for wallet connection
- **React** state and form hooks

---

## Notes

- `RAMP_ABI`, `BRIDGE_ADDRESS`, and `ERC20_ABI` should be imported from external constants.
- Assumes USDC uses 6 decimal places.
