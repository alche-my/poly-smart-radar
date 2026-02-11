"""One-time wallet setup for Polymarket trading bot.

Usage:
    python -m bot.setup_wallet              # Generate new wallet
    python -m bot.setup_wallet --key 0x...  # Use existing private key

Steps:
    1. Generate or accept private key
    2. Display Polygon address for USDC.e deposit
    3. Derive CLOB API credentials
    4. Set token approvals (requires POL/MATIC for gas)
    5. Output .env values to paste
"""

import argparse
import sys


USDC_E_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
CHAIN_ID = 137


def generate_wallet() -> tuple[str, str]:
    """Generate a new Ethereum private key and address."""
    from eth_account import Account

    account = Account.create()
    return account.key.hex(), account.address


def derive_clob_creds(private_key: str) -> dict:
    """Derive CLOB API credentials from private key."""
    from py_clob_client.client import ClobClient

    client = ClobClient(
        "https://clob.polymarket.com",
        key=private_key,
        chain_id=CHAIN_ID,
        signature_type=0,
    )
    creds = client.create_or_derive_api_creds()
    return {
        "api_key": creds.api_key,
        "api_secret": creds.api_secret,
        "api_passphrase": creds.api_passphrase,
    }


def set_allowances(private_key: str) -> list[str]:
    """Set token approvals for Polymarket exchange contracts.

    Uses py-clob-client's built-in set_allowances() which handles
    all required approvals (USDC.e + CTF for all exchange contracts).
    Returns list of transaction hashes.
    """
    from py_clob_client.client import ClobClient

    client = ClobClient(
        "https://clob.polymarket.com",
        key=private_key,
        chain_id=CHAIN_ID,
        signature_type=0,
    )
    creds = client.create_or_derive_api_creds()
    client.set_api_creds(creds)

    tx_hashes = []
    result = client.set_allowances()
    if isinstance(result, list):
        tx_hashes.extend(str(r) for r in result)
    elif result:
        tx_hashes.append(str(result))
    return tx_hashes


def main():
    parser = argparse.ArgumentParser(description="Set up Polymarket trading wallet")
    parser.add_argument(
        "--key",
        type=str,
        help="Existing private key (hex with 0x prefix)",
    )
    parser.add_argument(
        "--skip-approvals",
        action="store_true",
        help="Skip token approval step (if already done)",
    )
    args = parser.parse_args()

    print("=" * 50)
    print("POLYMARKET TRADING BOT - WALLET SETUP")
    print("=" * 50)
    print()

    # Step 1: Get or generate key
    if args.key:
        private_key = args.key
        from eth_account import Account

        account = Account.from_key(private_key)
        address = account.address
        print("Using provided private key")
    else:
        private_key, address = generate_wallet()
        print("Generated new wallet")

    print(f"Address: {address}")
    print()

    # Step 2: Show deposit instructions
    print("STEP 1: Send funds to this address on Polygon network:")
    print(f"  {address}")
    print()
    print(f"  USDC.e contract: {USDC_E_ADDRESS}")
    print(f"  Network: Polygon (chain ID {CHAIN_ID})")
    print("  Required: $10+ USDC.e + ~0.1 POL for gas")
    print()

    if not args.skip_approvals:
        input("Press ENTER after depositing USDC.e and POL...")
        print()

    # Step 3: Derive CLOB credentials
    print("STEP 2: Deriving CLOB API credentials...")
    try:
        creds = derive_clob_creds(private_key)
        print("  API credentials derived successfully")
    except Exception as e:
        print(f"  ERROR: {e}")
        sys.exit(1)
    print()

    # Step 4: Set approvals
    if not args.skip_approvals:
        print("STEP 3: Setting token approvals...")
        print("  This requires POL for gas fees on Polygon.")
        try:
            tx_hashes = set_allowances(private_key)
            for tx in tx_hashes:
                print(f"  TX: {tx}")
            print("  Approvals set successfully")
        except Exception as e:
            print(f"  ERROR: {e}")
            print("  You may need more POL for gas. Try again after adding POL.")
            print("  Use --skip-approvals to skip this step if already done.")
            sys.exit(1)
        print()
    else:
        print("STEP 3: Skipping token approvals (--skip-approvals)")
        print()

    # Step 5: Output .env values
    print("=" * 50)
    print("ADD THESE TO YOUR .env FILE:")
    print("=" * 50)
    print()
    print(f"BOT_ENABLED=true")
    print(f"BOT_PRIVATE_KEY={private_key}")
    print(f"BOT_WALLET_ADDRESS={address}")
    print(f"BOT_TELEGRAM_CHAT_ID=<your_bot_chat_id>")
    print()
    print("IMPORTANT: Keep BOT_PRIVATE_KEY secret! Never commit to git.")
    print()
    print("Setup complete. Start the radar with: python main.py")


if __name__ == "__main__":
    main()
