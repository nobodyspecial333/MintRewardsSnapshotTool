Free for anyone who owns a Solana token to use. I recommend you grab a bag of MintRewards (RWRD) though ... :) ca: 7yM17krfficCdkqg1CNRdptepryrxxFC4hayNmfVuRVc

# Solana Token Snapshot Tool

A Python tool to monitor and capture token holder snapshots for Solana SPL tokens. The tool continuously monitors bonding progress and adjusts snapshot frequency based on progress percentage.

## Features

- Captures snapshots of token holders and their balances
- Monitors bonding progress using DexScreener API
- Automatically adjusts snapshot frequency based on progress
- Saves snapshots in both CSV and JSON formats
- Implements rate limiting and retry logic for RPC calls
- Supports custom RPC endpoints

## Prerequisites

- Python 3.10 or higher
- pip (Python package installer)

## Installation

1. Clone the repository:
   ```bash
   git clone <repository-url>
   cd <repository-directory>
   ```

2. Install required dependencies:
   ```bash
   pip install pandas python-dotenv requests base58
   ```

## Configuration

Create a `.env` file in the project root directory with the following parameters:

```ini
HELIUS_API_KEY=your_helius_api_key_here
TOKEN_MINT_ADDRESS=your_token_mint_address
TARGET_MCAP_SOL=500
SNAPSHOT_DIR=snapshots
MIN_TOKEN_AMOUNT=1000000
```

### Parameters:
- `HELIUS_API_KEY`: Your Helius API key
- `TOKEN_MINT_ADDRESS`: The mint address of your SPL token
- `TARGET_MCAP_SOL`: Target market cap in SOL for bonding
- `SNAPSHOT_DIR`: Directory where snapshots will be saved
- `MIN_TOKEN_AMOUNT`: Minimum token amount to include in snapshots

## Usage

Run the script:
```bash
python token_snapshot.py
```

The script will:
1. Take an initial snapshot regardless of progress
2. Check bonding progress every 5 minutes
3. Take periodic snapshots based on progress:
   - Below 85%: Only initial snapshot
   - 85-90%: Daily snapshots
   - 90-95%: Every 4 hours
   - 95-97%: Every hour
   - 97-99%: Every 30 minutes
   - 99%+: Every 5 minutes
4. Take final snapshot when target is reached

## Output Files

Each snapshot generates two files:

1. CSV file (`snapshot_YYYYMMDD_HHMMSS.csv`) containing:
   - Holder addresses
   - Token balances
   - Timestamp

2. JSON file (`snapshot_YYYYMMDD_HHMMSS_info.json`) containing:
   - Timestamp
   - Total holders
   - Total supply
   - SOL volume
   - Progress percentage
   - Target reached status

## Rate Limiting

The tool implements rate limiting to work with public RPC endpoints:
- Adaptive request delays
- Maximum 3 retries for failed requests
- Super-exponential backoff for retries
- Circuit breaker protection

## Error Handling

The script includes comprehensive error handling and logging:
- Detailed error messages for RPC calls
- Retry logic for failed requests
- Automatic endpoint rotation on rate limits
- Verbose logging of all operations

## License

Free for anyone who owns a Solana token to use. I recommend you grab a bag of MintRewards (RWRD) though ... :) ca: 7yM17krfficCdkqg1CNRdptepryrxxFC4hayNmfVuRVc
